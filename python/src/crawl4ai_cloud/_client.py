"""The two clients: `Crawl4AI` (blocking calls) and `AsyncCrawl4AI` (the same methods, awaitable).

Both send every call through `_open`, which adds the headers, retries what is worth retrying and
turns an error answer into an exception (the shared rules are in `_http`).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any, Literal

import httpx

from . import _http
from ._http import BASE_URL, MAX_RETRIES, TIMEOUT
from .errors import APIConnectionError, APITimeoutError
from .types import (
    AnswerResult,
    ExtractResult,
    ScrapeBatchItem,
    ScrapeJob,
    ScrapeJobItem,
    ScrapeJobRetry,
    ScrapeResult,
    SearchResult,
    SerpResult,
    Tool,
    ToolEstimate,
    ToolList,
    ToolRun,
)

if TYPE_CHECKING:
    from typing_extensions import Self  # only for the type checker; typing.Self needs Python 3.11

Format = Literal["both", "md", "html"]
Proxy = Literal["standard", "extra"]
Engine = Literal["auto", "browser-light", "browser"]
Parse = bool | dict[str, bool]

# a job's status once it no longer changes by itself
_JOB_STOPPED = ("done", "paused")


class Crawl4AI:
    """The Crawl4AI Cloud client. Every method is one API call and blocks until the answer comes.

    Params:
        `api_key`: your key; when None it is read from `CRAWL4AI_API_KEY`. Without one only
            `tools.find` and `tools.get` work; every other call raises AuthenticationError.
        `base_url`: the API address. `timeout`: seconds to wait for one answer.
        `max_retries`: how many times a busy or rate-limited call is sent again.
        `http_client`: your own `httpx.Client` (for a proxy, say); the SDK does not close it.

    Example:
        from crawl4ai_cloud import Crawl4AI

        with Crawl4AI() as client:
            page = client.scrape("https://example.com")
            print(page.markdown)
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = BASE_URL,
        timeout: float = TIMEOUT,
        max_retries: int = MAX_RETRIES,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._headers = _http.headers(api_key)
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._timeout = timeout
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)
        self.tools = Tools(self)

    def close(self) -> None:
        """Closes the connections, unless you passed your own `http_client`."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _open(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        safe: bool = True,
        stream: bool = False,
        keyless: bool = False,
    ) -> httpx.Response:
        """Sends one request and returns the success answer, or raises.

        1. Send. A network failure is retried only when `safe`; a timeout is never retried
           (the server may still be working on it).
        2. On 429 / 503 (and 500 / 504 when `safe`) wait `retry_delay` and send again,
           up to `max_retries` times.
        3. Any other error answer raises the exception `error_from` picks.
        The body is read after the loop, so a 200 cut off midway is never sent again (it may
        already have run). With `stream`, the caller reads the body and must close the answer.
        Without a key only a `keyless` call is sent; any other raises AuthenticationError.
        """
        if not keyless:
            _http.require_key(self._headers)
        request = self._http.build_request(
            method,
            self._base_url + path,
            params=params,
            json=json,
            headers={**self._headers, **(headers or {})},
            timeout=self._timeout,
        )
        if "Authorization" not in self._headers:  # no key: never send the http_client's own credentials
            request.headers.pop("Authorization", None)
        for attempt in range(self._max_retries + 1):
            last = attempt == self._max_retries
            # ---- 1. Send ----
            try:
                response = self._http.send(request, stream=True, auth=None)
            except httpx.TimeoutException as e:
                raise APITimeoutError(f"No answer from {path} in time: {e}") from e
            except httpx.TransportError as e:
                if last or not safe:
                    raise APIConnectionError(f"{path}: {e}") from e
                time.sleep(_http.retry_delay(attempt))
                continue
            if response.is_success and stream:
                return response
            with _http.reading(path):
                response.read()  # the answer's JSON, or the error's body for error_from
            if response.is_success:
                return response
            # ---- 2. Retry ----
            error = _http.error_from(response)
            if last or not _http.should_retry(error, safe):
                # ---- 3. Raise ----
                raise error
            response.close()
            time.sleep(_http.retry_delay(attempt, response))
        raise AssertionError("unreachable: the last attempt returns or raises")

    def _lines(self, method: str, path: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
        """Sends one request and yields each line of its NDJSON answer as a dict, as it arrives.
        Lines end at `\n` only: httpx's `iter_lines` also splits at U+2028, which JSON text may hold."""
        response = self._open(method, path, stream=True, **kwargs)
        try:
            buffer = b""
            with _http.reading(path):
                for chunk in response.iter_bytes():
                    *lines, buffer = (buffer + chunk).split(b"\n")
                    for line in lines:
                        if line.strip():
                            yield _http.parse(line, path)
            if buffer.strip():
                yield _http.parse(buffer, path)
        finally:
            response.close()

    def scrape(
        self,
        url: str,
        *,
        format: Format | None = None,
        proxy: Proxy | None = None,
        country: str | None = None,
        parse: Parse | None = None,
        engine: Engine | None = None,
        bypass_cache: bool | None = None,
    ) -> ScrapeResult:
        """Fetches one page and returns it as clean Markdown and/or HTML (`POST /scrape`).

        Most pages take 1 to 2 s; a page that needs a real browser takes up to 90 s.
        A site that refuses every attempt raises BlockedError (`code` `blocked` or `login-wall`).

        Params:
            `format`: `both` (the default), `md` or `html`.
            `proxy`: `extra` tries harder when a site refuses; such a page costs 4x.
            `country`: two letters, the country the page is fetched from (`us`, `gb`).
            `parse`: True for the page's links, media, metadata and tables, or pick some,
                for example `{"links": True}`.
            `engine`: `browser-light` or `browser` to start at a browser; use only when the
                default misses content.
            `bypass_cache`: True to always fetch the page fresh, never from a cached copy.

        Example:
            from crawl4ai_cloud import Crawl4AI

            page = Crawl4AI().scrape("https://example.com", format="md")
            print(page.markdown)
        """
        fields = _http.body(
            url=url, format=format, proxy=proxy, country=country, parse=parse, engine=engine, bypass_cache=bypass_cache
        )
        return ScrapeResult.from_response(self._open("POST", "/scrape", json=fields))

    def scrape_batch(
        self,
        urls: list[str],
        *,
        format: Format | None = None,
        proxy: Proxy | None = None,
        country: str | None = None,
        parse: Parse | None = None,
        engine: Engine | None = None,
    ) -> Iterator[ScrapeBatchItem]:
        """Scrapes up to 50 URLs in one call and yields one item per URL as soon as its page is
        ready, in the order the pages finish (`POST /scrape/batch`).

        Each item has the page in `result` when `ok`, else the reason in `error`, and its own
        `cost`. The options are the ones of `scrape` and apply to every URL.

        Example:
            from crawl4ai_cloud import Crawl4AI

            for item in Crawl4AI().scrape_batch(["https://example.com", "https://example.org"]):
                print(item.url, item.result.markdown[:80] if item.ok else item.error)
        """
        fields = _http.body(urls=urls, format=format, proxy=proxy, country=country, parse=parse, engine=engine)
        for line in self._lines("POST", "/scrape/batch", json=fields):
            if "summary" not in line:  # the last line totals the batch; each item has its own cost
                yield ScrapeBatchItem.from_dict(line)

    def start_scrape_job(
        self,
        urls: list[str],
        *,
        format: Format | None = None,
        proxy: Proxy | None = None,
        country: str | None = None,
        parse: Parse | None = None,
        engine: Engine | None = None,
    ) -> ScrapeJob:
        """Starts a background job for up to 10,000 URLs and returns at once with its `job_id`
        (`POST /scrape/jobs`). Then `wait_scrape_job` and `get_scrape_job_results`.

        Every URL is charged the job's flat price; URLs that never got an answer are refunded
        when the job ends. Not retried on a 500, so a job is never started twice.

        Example:
            from crawl4ai_cloud import Crawl4AI

            client = Crawl4AI()
            job = client.start_scrape_job(["https://example.com", "https://example.org"])
            client.wait_scrape_job(job.job_id)
            for item in client.get_scrape_job_results(job.job_id):
                print(item.url, item.ok)
        """
        fields = _http.body(urls=urls, format=format, proxy=proxy, country=country, parse=parse, engine=engine)
        return ScrapeJob.from_response(self._open("POST", "/scrape/jobs", json=fields, safe=False))

    def get_scrape_job(self, job_id: str, *, full: bool | None = None) -> ScrapeJob:
        """Returns a job's `status`, `counts` and `usage` (`GET /scrape/jobs/{id}`).
        `full=True` adds every URL's detail (in `raw`).

        Example:
            from crawl4ai_cloud import Crawl4AI

            client = Crawl4AI()
            job = client.start_scrape_job(["https://example.com"])
            print(client.get_scrape_job(job.job_id).status)
        """
        params = _http.body(full=_http.flag(full))
        return ScrapeJob.from_response(self._open("GET", _http.job_path(job_id), params=params))

    def wait_scrape_job(self, job_id: str, *, poll_interval: float = 2.0, timeout: float | None = None) -> ScrapeJob:
        """Checks the job every `poll_interval` seconds and returns it once its status is `done`
        (or `paused`, which needs you to act). Raises APITimeoutError after `timeout` seconds.

        Example:
            from crawl4ai_cloud import Crawl4AI

            client = Crawl4AI()
            job = client.start_scrape_job(["https://example.com"])
            print(client.wait_scrape_job(job.job_id, timeout=600).counts)
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            job = self.get_scrape_job(job_id)
            if job.status in _JOB_STOPPED:
                return job
            left = poll_interval if deadline is None else deadline - time.monotonic()
            if left <= 0:
                raise APITimeoutError(f"Job {job_id} is still {job.status} after {timeout} s")
            time.sleep(min(poll_interval, left))

    def get_scrape_job_results(self, job_id: str) -> Iterator[ScrapeJobItem]:
        """Yields a job's results, one item per URL, fetching page after page for you
        (`GET /scrape/jobs/{id}/results`). Read them after `wait_scrape_job`.

        Example:
            from crawl4ai_cloud import Crawl4AI

            client = Crawl4AI()
            job = client.start_scrape_job(["https://example.com"])
            client.wait_scrape_job(job.job_id)
            for item in client.get_scrape_job_results(job.job_id):
                print(item.url, item.markdown[:80] if item.ok else item.error)
        """
        after = 0
        while True:
            read = 0
            for line in self._lines("GET", _http.job_path(job_id, "/results"), params={"after": after}):
                read += 1
                yield ScrapeJobItem.from_dict(line)
            if read == 0:  # an empty page: no more results
                return
            after += read

    def retry_scrape_job(self, job_id: str) -> ScrapeJobRetry:
        """Runs a job's failed URLs again (`POST /scrape/jobs/{id}/retry`); `retrying` says how many.

        Example:
            from crawl4ai_cloud import Crawl4AI

            client = Crawl4AI()
            job = client.start_scrape_job(["https://example.com"])
            client.wait_scrape_job(job.job_id)
            print(client.retry_scrape_job(job.job_id).retrying)
        """
        return ScrapeJobRetry.from_response(self._open("POST", _http.job_path(job_id, "/retry"), safe=False))

    def search(self, q: str, *, rich: bool | None = None, deep: bool | None = None) -> SearchResult:
        """Searches the web and returns ranked, cleaned results (`GET /search`).

        Params:
            `q`: the query, at most 512 characters.
            `rich`: True adds follow-up questions, related queries, an entity card, videos and news.
            `deep`: True also reads the top 10 pages and puts each page's text in its result's
                `markdown`. Up to 5 s slower; each page with text costs one plain scrape page.

        Example:
            from crawl4ai_cloud import Crawl4AI

            for result in Crawl4AI().search("rust web crawler").results:
                print(result.title, result.url)
        """
        params = _http.body(q=q, rich=_http.flag(rich), deep=_http.flag(deep))
        return SearchResult.from_response(self._open("GET", "/search", params=params))

    def serp(
        self,
        q: str,
        *,
        country: str | None = None,
        language: str | None = None,
        location: str | None = None,
        num: int | None = None,
        page: int | None = None,
        time: Literal["hour", "day", "week", "month", "year"] | None = None,
        fresh: bool | None = None,
        source: Literal["auto", "google"] | None = None,
    ) -> SerpResult:
        """Returns Google's results page as data: true ranks and every block Google showed
        (`GET /serp`, beta).

        Params:
            `q`: the query, at most 512 characters.
            `country`, `language`: the Google page's country (`us`) and language (`en`).
            `location`: a city or region, for example `Austin, TX`.
            `num`: results per page, 10 to 100 in steps of 10. `page`: which page, in steps of `num`.
            `time`: only results from the past hour, day, week, month or year.
            `fresh`: True skips the cache, at the live price.
            `source`: `google` for the road that also returns the AI Overview.

        Example:
            from crawl4ai_cloud import Crawl4AI

            for result in Crawl4AI().serp("best crm software", country="us").results:
                print(result.position, result.domain)
        """
        params = _http.body(
            q=q, country=country, language=language, location=location, num=num, page=page,
            time=time, fresh=_http.flag(fresh), source=source,
        )
        return SerpResult.from_response(self._open("GET", "/serp", params=params))

    def answer(self, q: str, *, schema: dict[str, Any] | None = None, deep: bool | None = None) -> AnswerResult:
        """Answers a question from the web, with its sources (`GET /answer`, experimental).

        When there is no answer, `answered` is False and the call costs nothing.

        Params:
            `q`: the question, or a whole prompt, at most 4,000 characters.
            `schema`: a JSON Schema; `answer.text` is then JSON of that shape (parse it with json.loads).
            `deep`: False returns only an answer that is readily available, without reading pages.

        Example:
            from crawl4ai_cloud import Crawl4AI

            result = Crawl4AI().answer("why is the sky blue")
            if result.answered:
                print(result.answer.text)
        """
        params = _http.body(q=q, schema=_http.schema_param(schema), deep=_http.flag(deep))
        return AnswerResult.from_response(self._open("GET", "/answer", params=params))

    def extract(
        self,
        url: str | None = None,
        *,
        content: str | None = None,
        instruction: str | None = None,
        schema: dict[str, Any] | None = None,
        example: Any = None,
    ) -> ExtractResult:
        """Pulls structured data out of a page with a language model (`POST /extract`).

        Give `url` (the page is fetched for you) or `content` (your own text, Markdown or HTML),
        plus `instruction` and/or `schema`.

        Params:
            `instruction`: what to pull out, in plain English.
            `schema`: a JSON Schema each record must match.
            `example`: a sample of the shape you want.

        Example:
            from crawl4ai_cloud import Crawl4AI

            result = Crawl4AI().extract("https://news.ycombinator.com", instruction="the top 3 story titles")
            print(result.data)
        """
        fields = _http.body(url=url, content=content, instruction=instruction, schema=schema, example=example)
        return ExtractResult.from_response(self._open("POST", "/extract", json=fields))


class AsyncCrawl4AI:
    """The async Crawl4AI Cloud client: the methods of `Crawl4AI`, awaitable. `scrape_batch` and
    `get_scrape_job_results` are async iterators. See `Crawl4AI` for every method's docs.

    Example:
        import asyncio
        from crawl4ai_cloud import AsyncCrawl4AI

        async def main():
            async with AsyncCrawl4AI() as client:
                page = await client.scrape("https://example.com")
                print(page.markdown)

        asyncio.run(main())
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = BASE_URL,
        timeout: float = TIMEOUT,
        max_retries: int = MAX_RETRIES,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._headers = _http.headers(api_key)
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._timeout = timeout
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self.tools = AsyncTools(self)

    async def close(self) -> None:
        """Closes the connections, unless you passed your own `http_client`."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def _open(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        safe: bool = True,
        stream: bool = False,
        keyless: bool = False,
    ) -> httpx.Response:
        """Sends one request and returns the success answer, or raises. The steps are the ones of
        `Crawl4AI._open`."""
        if not keyless:
            _http.require_key(self._headers)
        request = self._http.build_request(
            method,
            self._base_url + path,
            params=params,
            json=json,
            headers={**self._headers, **(headers or {})},
            timeout=self._timeout,
        )
        if "Authorization" not in self._headers:  # no key: never send the http_client's own credentials
            request.headers.pop("Authorization", None)
        for attempt in range(self._max_retries + 1):
            last = attempt == self._max_retries
            try:
                response = await self._http.send(request, stream=True, auth=None)
            except httpx.TimeoutException as e:
                raise APITimeoutError(f"No answer from {path} in time: {e}") from e
            except httpx.TransportError as e:
                if last or not safe:
                    raise APIConnectionError(f"{path}: {e}") from e
                await asyncio.sleep(_http.retry_delay(attempt))
                continue
            if response.is_success and stream:
                return response
            with _http.reading(path):
                await response.aread()
            if response.is_success:
                return response
            error = _http.error_from(response)
            if last or not _http.should_retry(error, safe):
                raise error
            await response.aclose()
            await asyncio.sleep(_http.retry_delay(attempt, response))
        raise AssertionError("unreachable: the last attempt returns or raises")

    async def _lines(self, method: str, path: str, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        """Sends one request and yields each line of its NDJSON answer as a dict, as it arrives.
        Lines end at `\n` only, as in `Crawl4AI._lines`."""
        response = await self._open(method, path, stream=True, **kwargs)
        try:
            buffer = b""
            with _http.reading(path):
                async for chunk in response.aiter_bytes():
                    *lines, buffer = (buffer + chunk).split(b"\n")
                    for line in lines:
                        if line.strip():
                            yield _http.parse(line, path)
            if buffer.strip():
                yield _http.parse(buffer, path)
        finally:
            await response.aclose()

    async def scrape(
        self,
        url: str,
        *,
        format: Format | None = None,
        proxy: Proxy | None = None,
        country: str | None = None,
        parse: Parse | None = None,
        engine: Engine | None = None,
        bypass_cache: bool | None = None,
    ) -> ScrapeResult:
        """One page as Markdown and/or HTML. See `Crawl4AI.scrape`.

        Example:
            page = await AsyncCrawl4AI().scrape("https://example.com")
        """
        fields = _http.body(
            url=url, format=format, proxy=proxy, country=country, parse=parse, engine=engine, bypass_cache=bypass_cache
        )
        return ScrapeResult.from_response(await self._open("POST", "/scrape", json=fields))

    async def scrape_batch(
        self,
        urls: list[str],
        *,
        format: Format | None = None,
        proxy: Proxy | None = None,
        country: str | None = None,
        parse: Parse | None = None,
        engine: Engine | None = None,
    ) -> AsyncIterator[ScrapeBatchItem]:
        """Up to 50 URLs, one item per URL as it is ready. See `Crawl4AI.scrape_batch`.

        Example:
            async for item in AsyncCrawl4AI().scrape_batch(["https://example.com"]):
                print(item.url, item.ok)
        """
        fields = _http.body(urls=urls, format=format, proxy=proxy, country=country, parse=parse, engine=engine)
        async for line in self._lines("POST", "/scrape/batch", json=fields):
            if "summary" not in line:
                yield ScrapeBatchItem.from_dict(line)

    async def start_scrape_job(
        self,
        urls: list[str],
        *,
        format: Format | None = None,
        proxy: Proxy | None = None,
        country: str | None = None,
        parse: Parse | None = None,
        engine: Engine | None = None,
    ) -> ScrapeJob:
        """Starts a background job for up to 10,000 URLs. See `Crawl4AI.start_scrape_job`.

        Example:
            job = await AsyncCrawl4AI().start_scrape_job(["https://example.com"])
        """
        fields = _http.body(urls=urls, format=format, proxy=proxy, country=country, parse=parse, engine=engine)
        return ScrapeJob.from_response(await self._open("POST", "/scrape/jobs", json=fields, safe=False))

    async def get_scrape_job(self, job_id: str, *, full: bool | None = None) -> ScrapeJob:
        """A job's status, counts and usage. See `Crawl4AI.get_scrape_job`.

        Example:
            job = await client.get_scrape_job(job_id)
        """
        params = _http.body(full=_http.flag(full))
        return ScrapeJob.from_response(await self._open("GET", _http.job_path(job_id), params=params))

    async def wait_scrape_job(
        self, job_id: str, *, poll_interval: float = 2.0, timeout: float | None = None
    ) -> ScrapeJob:
        """Waits until the job is `done` or `paused`. See `Crawl4AI.wait_scrape_job`.

        Example:
            job = await client.wait_scrape_job(job_id, timeout=600)
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            job = await self.get_scrape_job(job_id)
            if job.status in _JOB_STOPPED:
                return job
            left = poll_interval if deadline is None else deadline - time.monotonic()
            if left <= 0:
                raise APITimeoutError(f"Job {job_id} is still {job.status} after {timeout} s")
            await asyncio.sleep(min(poll_interval, left))

    async def get_scrape_job_results(self, job_id: str) -> AsyncIterator[ScrapeJobItem]:
        """A job's results, one item per URL, every page. See `Crawl4AI.get_scrape_job_results`.

        Example:
            async for item in client.get_scrape_job_results(job_id):
                print(item.url, item.ok)
        """
        after = 0
        while True:
            read = 0
            async for line in self._lines("GET", _http.job_path(job_id, "/results"), params={"after": after}):
                read += 1
                yield ScrapeJobItem.from_dict(line)
            if read == 0:
                return
            after += read

    async def retry_scrape_job(self, job_id: str) -> ScrapeJobRetry:
        """Runs a job's failed URLs again. See `Crawl4AI.retry_scrape_job`.

        Example:
            print((await client.retry_scrape_job(job_id)).retrying)
        """
        return ScrapeJobRetry.from_response(await self._open("POST", _http.job_path(job_id, "/retry"), safe=False))

    async def search(self, q: str, *, rich: bool | None = None, deep: bool | None = None) -> SearchResult:
        """Web search. See `Crawl4AI.search`.

        Example:
            results = (await AsyncCrawl4AI().search("rust web crawler")).results
        """
        params = _http.body(q=q, rich=_http.flag(rich), deep=_http.flag(deep))
        return SearchResult.from_response(await self._open("GET", "/search", params=params))

    async def serp(
        self,
        q: str,
        *,
        country: str | None = None,
        language: str | None = None,
        location: str | None = None,
        num: int | None = None,
        page: int | None = None,
        time: Literal["hour", "day", "week", "month", "year"] | None = None,
        fresh: bool | None = None,
        source: Literal["auto", "google"] | None = None,
    ) -> SerpResult:
        """Google's results page as data. See `Crawl4AI.serp`.

        Example:
            results = (await AsyncCrawl4AI().serp("best crm software")).results
        """
        params = _http.body(
            q=q, country=country, language=language, location=location, num=num, page=page,
            time=time, fresh=_http.flag(fresh), source=source,
        )
        return SerpResult.from_response(await self._open("GET", "/serp", params=params))

    async def answer(self, q: str, *, schema: dict[str, Any] | None = None, deep: bool | None = None) -> AnswerResult:
        """A direct answer with sources. See `Crawl4AI.answer`.

        Example:
            result = await AsyncCrawl4AI().answer("why is the sky blue")
        """
        params = _http.body(q=q, schema=_http.schema_param(schema), deep=_http.flag(deep))
        return AnswerResult.from_response(await self._open("GET", "/answer", params=params))

    async def extract(
        self,
        url: str | None = None,
        *,
        content: str | None = None,
        instruction: str | None = None,
        schema: dict[str, Any] | None = None,
        example: Any = None,
    ) -> ExtractResult:
        """Structured data from a page. See `Crawl4AI.extract`.

        Example:
            result = await AsyncCrawl4AI().extract("https://example.com", instruction="the page title")
        """
        fields = _http.body(url=url, content=content, instruction=instruction, schema=schema, example=example)
        return ExtractResult.from_response(await self._open("POST", "/extract", json=fields))


class Tools:
    """The Toolkit: every Crawl4AI tool, called the same way. Reach it as `client.tools`.

    A tool is one kind of data: `scrape`, `search` and `extract` work on any website, and a ready
    tool exists for each supported site (`amazon-product`, `linkedin-company`, ...). Find one with
    `find`, read its inputs with `get`, price a run with `estimate`, run it with `run`, or
    run it on many inputs as one job with `batch`.

    Example:
        from crawl4ai_cloud import Crawl4AI

        client = Crawl4AI()
        tool = client.tools.find("amazon product").tools[0]
        print(client.tools.run(tool.id, {"product": "B0F5HSNDXF"}).rows)
    """

    def __init__(self, client: Crawl4AI) -> None:
        self._client = client

    def find(
        self,
        q: str | None = None,
        *,
        kind: Literal["pages", "search", "people", "sites"] | None = None,
        source: str | None = None,
        status: Literal["verified", "beta", "failing"] | None = None,
        essential: bool | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> ToolList:
        """Lists the tools, best match for `q` first (`GET /tools`). Free, and works without a key.

        Params:
            `q`: a few words; every word must be in the tool's id, name, site, summary or search words.
            `kind`: `pages`, `search`, `people` or `sites`. `source`: one site, for example `amazon`.
            `status`: `verified`, `beta` or `failing`. `essential`: True for the tools that work on any site.
            `limit`: tools per page (50 by default, at most 200). `cursor`: `next_cursor` of the last page.

        Example:
            from crawl4ai_cloud import Crawl4AI

            for tool in Crawl4AI().tools.find("amazon").tools:
                print(tool.id, tool.cost, tool.summary)
        """
        params = _http.body(
            q=q, kind=kind, source=source, status=status, essential="true" if essential else None, limit=limit, cursor=cursor
        )
        return ToolList.from_dict(_http.parse(self._client._open("GET", "/tools", params=params, keyless=True).content, "/tools"))

    def get(self, tool_id: str) -> Tool:
        """One tool in full: its `inputs`, `output`, `cost`, `examples` and `input_schema` (`GET /tools/{id}`).
        Free, and works without a key. An unknown id raises NotFoundError; its `body["did_you_mean"]` lists the closest ids.

        Example:
            from crawl4ai_cloud import Crawl4AI

            tool = Crawl4AI().tools.get("amazon-product")
            print([i["name"] for i in tool.inputs])
        """
        path = _http.tool_path(tool_id)
        return Tool.from_dict(_http.parse(self._client._open("GET", path, keyless=True).content, path))

    def estimate(self, tool_id: str, inputs: dict[str, Any]) -> ToolEstimate:
        """What a run with these `inputs` would cost, before it runs (`POST /tools/{id}/estimate`). Free.

        Example:
            from crawl4ai_cloud import Crawl4AI

            print(Crawl4AI().tools.estimate("amazon-product", {"product": "B0F5HSNDXF"}).data["text"])
        """
        path = _http.tool_path(tool_id, "/estimate")
        return ToolEstimate.from_dict(_http.parse(self._client._open("POST", path, json=inputs).content, path))

    def run(self, tool_id: str, inputs: dict[str, Any], *, fresh: bool | None = None) -> ToolRun:
        """Runs a tool on your key, at the price of the tool's own address (`POST /tools/{id}`).

        A tool that returns rows puts them in `rows`; the rest of its answer is in `data`. A failed
        run is not charged. The call is never sent twice after a 500 or a lost connection, since
        it may already have run and been charged.

        Params:
            `inputs`: the tool's inputs, as `get` lists them. `fresh`: True skips the cache, at the live price.

        Raises BadRequestError (`invalid_input`, the problem in the message), NotFoundError
        (`tool_not_found`) and ServerError (`tool_failing`: the tool's daily check is failing; not retried).

        Example:
            from crawl4ai_cloud import Crawl4AI

            run = Crawl4AI().tools.run("scrape", {"url": "https://example.com"})
            print(run.data["markdown"], run.usage)
        """
        headers = {"Crawl4AI-Fresh": "true"} if fresh else None
        return ToolRun.from_response(
            self._client._open("POST", _http.tool_path(tool_id), json=inputs, headers=headers, safe=False)
        )

    def batch(self, tool_id: str, inputs: list[dict[str, Any]]) -> ToolRun:
        """Runs a tool on many inputs as one background job and returns at once (`POST /tools/batch`).
        The job is in `data`: wait for it with `wait_scrape_job(run.data["job_id"])`, then read it
        with `get_scrape_job_results`. A tool with no batch raises BadRequestError. Never sent
        twice after a 500 or a lost connection, so a job is never started twice.

        Example:
            from crawl4ai_cloud import Crawl4AI

            client = Crawl4AI()
            run = client.tools.batch("scrape", [{"url": "https://example.com"}, {"url": "https://example.org"}])
            client.wait_scrape_job(run.data["job_id"])
            for item in client.get_scrape_job_results(run.data["job_id"]):
                print(item.url, item.ok)
        """
        fields = {"tool": tool_id, "inputs": inputs}
        return ToolRun.from_response(self._client._open("POST", "/tools/batch", json=fields, safe=False))


class AsyncTools:
    """The Toolkit for `AsyncCrawl4AI`, reached as `client.tools`. The methods are the ones of `Tools`,
    each awaited.

    Example:
        import asyncio
        from crawl4ai_cloud import AsyncCrawl4AI

        async def main():
            async with AsyncCrawl4AI() as client:
                print((await client.tools.find("youtube")).tools[0].id)

        asyncio.run(main())
    """

    def __init__(self, client: AsyncCrawl4AI) -> None:
        self._client = client

    async def find(
        self,
        q: str | None = None,
        *,
        kind: Literal["pages", "search", "people", "sites"] | None = None,
        source: str | None = None,
        status: Literal["verified", "beta", "failing"] | None = None,
        essential: bool | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> ToolList:
        """Lists the tools. See `Tools.find`."""
        params = _http.body(
            q=q, kind=kind, source=source, status=status, essential="true" if essential else None, limit=limit, cursor=cursor
        )
        response = await self._client._open("GET", "/tools", params=params, keyless=True)
        return ToolList.from_dict(_http.parse(response.content, "/tools"))

    async def get(self, tool_id: str) -> Tool:
        """One tool in full. See `Tools.get`."""
        path = _http.tool_path(tool_id)
        return Tool.from_dict(_http.parse((await self._client._open("GET", path, keyless=True)).content, path))

    async def estimate(self, tool_id: str, inputs: dict[str, Any]) -> ToolEstimate:
        """What a run would cost. See `Tools.estimate`."""
        path = _http.tool_path(tool_id, "/estimate")
        return ToolEstimate.from_dict(_http.parse((await self._client._open("POST", path, json=inputs)).content, path))

    async def run(self, tool_id: str, inputs: dict[str, Any], *, fresh: bool | None = None) -> ToolRun:
        """Runs a tool. See `Tools.run`."""
        headers = {"Crawl4AI-Fresh": "true"} if fresh else None
        return ToolRun.from_response(
            await self._client._open("POST", _http.tool_path(tool_id), json=inputs, headers=headers, safe=False)
        )

    async def batch(self, tool_id: str, inputs: list[dict[str, Any]]) -> ToolRun:
        """Runs a tool on many inputs as one background job. See `Tools.batch`."""
        fields = {"tool": tool_id, "inputs": inputs}
        return ToolRun.from_response(await self._client._open("POST", "/tools/batch", json=fields, safe=False))
