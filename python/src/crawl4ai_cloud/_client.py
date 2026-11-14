"""The two clients: `Crawl4AI` (blocking calls) and `AsyncCrawl4AI` (the same methods, awaitable).

Both send every call through `_open`, which adds the headers, retries what is worth retrying and
turns an error answer into an exception (the shared rules are in `_http`).
"""

from __future__ import annotations

import asyncio
import json
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
        `api_key`: your key; when None it is read from `CRAWL4AI_API_KEY`.
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
        safe: bool = True,
        stream: bool = False,
    ) -> httpx.Response:
        """Sends one request and returns the success answer, or raises.

        1. Send. A network failure is retried only when `safe`; a timeout is never retried
           (the server may still be working on it).
        2. On 429 / 503 (and 500 / 504 when `safe`) wait `retry_delay` and send again,
           up to `max_retries` times.
        3. Any other error answer raises the exception `error_from` picks.
        With `stream`, the caller reads the body and must close the answer.
        """
        request = self._http.build_request(
            method, self._base_url + path, params=params, json=json, headers=self._headers, timeout=self._timeout
        )
        for attempt in range(self._max_retries + 1):
            last = attempt == self._max_retries
            # ---- 1. Send ----
            try:
                response = self._http.send(request, stream=stream)
            except httpx.TimeoutException as e:
                raise APITimeoutError(f"No answer from {path} in time: {e}") from e
            except httpx.TransportError as e:
                if last or not safe:
                    raise APIConnectionError(f"{path}: {e}") from e
                time.sleep(_http.retry_delay(attempt))
                continue
            if response.is_success:
                return response
            # ---- 2. Retry ----
            response.read()  # a streamed error answer: load its body for error_from
            if last or not _http.should_retry(response.status_code, safe):
                # ---- 3. Raise ----
                raise _http.error_from(response)
            response.close()
            time.sleep(_http.retry_delay(attempt, response))
        raise AssertionError("unreachable: the last attempt returns or raises")

    def _lines(self, method: str, path: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
        """Sends one request and yields each line of its NDJSON answer as a dict, as it arrives."""
        response = self._open(method, path, stream=True, **kwargs)
        try:
            for line in response.iter_lines():
                if line.strip():
                    yield json.loads(line)
        except httpx.TimeoutException as e:
            raise APITimeoutError(f"{path}: the answer stopped coming in time: {e}") from e
        except httpx.TransportError as e:
            raise APIConnectionError(f"{path}: the answer stopped: {e}") from e
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

    def search(self, q: str, *, rich: bool | None = None) -> SearchResult:
        """Searches the web and returns ranked, cleaned results (`GET /search`).

        Params:
            `q`: the query, at most 512 characters.
            `rich`: True adds follow-up questions, related queries, an entity card, videos and news.

        Example:
            from crawl4ai_cloud import Crawl4AI

            for result in Crawl4AI().search("rust web crawler").results:
                print(result.title, result.url)
        """
        params = _http.body(q=q, rich=_http.flag(rich))
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
        safe: bool = True,
        stream: bool = False,
    ) -> httpx.Response:
        """Sends one request and returns the success answer, or raises. The steps are the ones of
        `Crawl4AI._open`."""
        request = self._http.build_request(
            method, self._base_url + path, params=params, json=json, headers=self._headers, timeout=self._timeout
        )
        for attempt in range(self._max_retries + 1):
            last = attempt == self._max_retries
            try:
                response = await self._http.send(request, stream=stream)
            except httpx.TimeoutException as e:
                raise APITimeoutError(f"No answer from {path} in time: {e}") from e
            except httpx.TransportError as e:
                if last or not safe:
                    raise APIConnectionError(f"{path}: {e}") from e
                await asyncio.sleep(_http.retry_delay(attempt))
                continue
            if response.is_success:
                return response
            await response.aread()
            if last or not _http.should_retry(response.status_code, safe):
                raise _http.error_from(response)
            await response.aclose()
            await asyncio.sleep(_http.retry_delay(attempt, response))
        raise AssertionError("unreachable: the last attempt returns or raises")

    async def _lines(self, method: str, path: str, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        """Sends one request and yields each line of its NDJSON answer as a dict, as it arrives."""
        response = await self._open(method, path, stream=True, **kwargs)
        try:
            async for line in response.aiter_lines():
                if line.strip():
                    yield json.loads(line)
        except httpx.TimeoutException as e:
            raise APITimeoutError(f"{path}: the answer stopped coming in time: {e}") from e
        except httpx.TransportError as e:
            raise APIConnectionError(f"{path}: the answer stopped: {e}") from e
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

    async def search(self, q: str, *, rich: bool | None = None) -> SearchResult:
        """Web search. See `Crawl4AI.search`.

        Example:
            results = (await AsyncCrawl4AI().search("rust web crawler")).results
        """
        params = _http.body(q=q, rich=_http.flag(rich))
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
