"""The results the SDK returns: one dataclass per answer shape.

Every result keeps the full JSON answer in `raw`, so a field the server adds later is never lost.
A field the server did not send is None.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any, ClassVar

import httpx

from . import _http

if TYPE_CHECKING:
    from typing_extensions import Self  # only for the type checker; typing.Self needs Python 3.11


def _credits(value: Any) -> float | None:
    """Turns a credits figure (the server sends text like "0.500") into a float. None, or text
    that is not a number, is None: a bad header must not fail a call that was already charged."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(kw_only=True, slots=True)
class Model:
    """The base of every result: `raw` holds the JSON object it was read from."""

    raw: dict[str, Any] = field(repr=False)

    # field name -> the Model class its value (an object or a list of objects) is read into
    _nested: ClassVar[dict[str, type[Model]]] = {}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Reads the known fields of `data` into this class; nested objects become their own class."""
        values: dict[str, Any] = {"raw": data}
        # a Response's cost fields come from the headers, in from_response
        skip = _HEADER_FIELDS if issubclass(cls, Response) else ()
        for f in fields(cls):
            if f.name == "raw" or f.name in skip:
                continue
            value = data.get(f.name)
            nested = cls._nested.get(f.name)
            if nested is not None and value is not None:
                value = [nested.from_dict(v) for v in value] if isinstance(value, list) else nested.from_dict(value)
            values[f.name] = value
        return cls(**values)


@dataclass(kw_only=True, slots=True)
class Response(Model):
    """A whole answer to one call. Adds the cost headers: credits this call cost (`cost`),
    credits left on the account (`balance`) and credits left under this month's plan (`allowance_left`)."""

    cost: float | None = None
    balance: float | None = None
    allowance_left: float | None = None

    @classmethod
    def from_response(cls, response: httpx.Response) -> Self:
        """Reads the JSON body and the `x-c4-cost`, `x-c4-balance`, `x-c4-allowance-left` headers."""
        result = cls.from_dict(_http.parse(response.content, response.request.url.path))
        result.cost = _credits(response.headers.get("x-c4-cost"))
        result.balance = _credits(response.headers.get("x-c4-balance"))
        result.allowance_left = _credits(response.headers.get("x-c4-allowance-left"))
        return result


_HEADER_FIELDS = {f.name for f in fields(Response)} - {"raw"}


@dataclass(kw_only=True, slots=True)
class Link(Model):
    """A page someone can open: its `title` and `url`."""

    title: str | None = None
    url: str | None = None


@dataclass(kw_only=True, slots=True)
class ScrapeResult(Response):
    """One page from `scrape`. `markdown` and `html` are set by the `format` you asked for."""

    ok: bool | None = None
    markdown: str | None = None
    html: str | None = None
    engine: str | None = None
    cache: str | None = None
    reason: str | None = None
    ms: int | None = None
    bytes: int | None = None
    text_len: int | None = None
    content_hash: str | None = None
    exit: str | None = None
    ladder: list[dict[str, Any]] | None = None
    usage: dict[str, Any] | None = None


@dataclass(kw_only=True, slots=True)
class ScrapeBatchItem(Model):
    """One URL's line from `scrape_batch`: the page in `result` when `ok`, else the reason in `error`.
    `cost` is what this URL cost, in credits."""

    url: str | None = None
    ok: bool | None = None
    result: ScrapeResult | None = None
    error: str | None = None
    cost: float | None = None
    effort: int | None = None

    _nested: ClassVar[dict[str, type[Model]]] = {"result": ScrapeResult}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Reads the line; `cost` comes as text and becomes a float."""
        item = super(ScrapeBatchItem, cls).from_dict(data)
        item.cost = _credits(item.cost)
        return item


@dataclass(kw_only=True, slots=True)
class ScrapeJob(Response):
    """A background scrape job. `status` is `pending`, `running` or `done`; `counts` holds the
    number of URLs `pending`, `done` and in `error`; `usage` what the job cost."""

    job_id: str | None = None
    status: str | None = None
    counts: dict[str, int] | None = None
    usage: dict[str, Any] | None = None


@dataclass(kw_only=True, slots=True)
class ScrapeJobItem(Model):
    """One URL's line from a job's results. On failure `ok` is False and `error` holds
    `class` and `detail`."""

    url: str | None = None
    ok: bool | None = None
    markdown: str | None = None
    html: str | None = None
    content_hash: str | None = None
    error: dict[str, Any] | None = None
    seq: int | None = None


@dataclass(kw_only=True, slots=True)
class ScrapeJobRetry(Response):
    """The answer to `retry_scrape_job`: `retrying` is the number of failed URLs queued again."""

    job_id: str | None = None
    retrying: int | None = None
    usage: dict[str, Any] | None = None


@dataclass(kw_only=True, slots=True)
class SearchItem(Model):
    """One web result. `source` is `gg` or `gs` for a live result, `index` for the Crawl4AI index.
    `markdown` (only with `deep=True`) is the page's text, absent when the page gave none in time."""

    title: str | None = None
    url: str | None = None
    snippet: str | None = None
    source: str | None = None
    markdown: str | None = None


@dataclass(kw_only=True, slots=True)
class SearchResult(Response):
    """The answer to `search`. `rich` (only with `rich=True`) holds follow-up questions, related
    queries, an entity card and more, each key only when it was on the page. `deep` and
    `usage["deep_pages"]` (only with `deep=True`) count the pages read and the pages charged."""

    results: list[SearchItem] | None = None
    rich: dict[str, Any] | None = None
    deep: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None

    _nested: ClassVar[dict[str, type[Model]]] = {"results": SearchItem}


@dataclass(kw_only=True, slots=True)
class SerpItem(Model):
    """One organic Google result. `position` counts organic results only; `position_absolute`
    counts every block on the page."""

    position: int | None = None
    position_absolute: int | None = None
    title: str | None = None
    url: str | None = None
    domain: str | None = None
    displayed_url: str | None = None
    snippet: str | None = None
    date: str | None = None
    sitelinks: list[Link] | None = None

    _nested: ClassVar[dict[str, type[Model]]] = {"sitelinks": Link}


@dataclass(kw_only=True, slots=True)
class SerpResult(Response):
    """The answer to `serp`: Google's results page. `blocks` names every block on the page in order;
    the blocks not listed as fields here (`knowledge_panel`, `local_pack`, ...) are in `raw`."""

    search: dict[str, Any] | None = None
    results: list[SerpItem] | None = None
    blocks: list[str] | None = None
    total_results: int | None = None
    source: str | None = None
    empty_reason: str | None = None
    cached: bool | None = None
    age_s: int | None = None
    pages: dict[str, Any] | None = None
    ai_overview: dict[str, Any] | None = None
    people_also_ask: list[str] | None = None
    related_searches: list[str] | None = None
    ms: int | None = None

    _nested: ClassVar[dict[str, type[Model]]] = {"results": SerpItem}


@dataclass(kw_only=True, slots=True)
class Answer(Model):
    """The answer `text` (JSON text when a schema was given), who wrote it (`source`) and the pages
    it drew on (`sources`)."""

    text: str | None = None
    source: str | None = None
    sources: list[Link] | None = None

    _nested: ClassVar[dict[str, type[Model]]] = {"sources": Link}


@dataclass(kw_only=True, slots=True)
class AnswerResult(Response):
    """The answer to `answer`. `answered` is False when there is no direct answer yet."""

    answered: bool | None = None
    answer: Answer | None = None
    query: str | None = None
    experimental: bool | None = None

    _nested: ClassVar[dict[str, type[Model]]] = {"answer": Answer}


@dataclass(kw_only=True, slots=True)
class ExtractResult(Response):
    """The answer to `extract`: the records in `data`, in the shape of your schema when you gave one."""

    ok: bool | None = None
    url: str | None = None
    data: Any = None
    usage: dict[str, Any] | None = None
    ms: int | None = None


@dataclass(kw_only=True, slots=True)
class ToolSummary(Model):
    """One tool in the list `tools.find` returns: `id`, `name` (`[lead word, rest]`), `source` (the
    site), `kind`, `summary`, `cost` (text like `1 cr`), `typical` (a typical run time), `status`
    (`verified`, `beta` or `failing`), `essential`, `beta` and `inputs` (the input names; a name
    ending in `*` is required). `tools.get` gives the tool in full."""

    id: str | None = None
    name: list[str] | None = None
    source: str | None = None
    kind: str | None = None
    summary: str | None = None
    cost: str | None = None
    typical: str | None = None
    status: str | None = None
    essential: bool | None = None
    beta: bool | None = None
    inputs: list[str] | None = None


@dataclass(kw_only=True, slots=True)
class Tool(Model):
    """One tool in full, from `tools.get`: the fields of `ToolSummary`, except that `name` is
    `{"lead": ..., "rest": ...}`, `cost` is `{"text": ..., "rule": ...}` and each of `inputs` has
    `name`, `type`, `required`, `help` and `example`; plus `description`, `output`
    (`output["fields"]`), `examples` and `input_schema` (a JSON Schema of the inputs)."""

    id: str | None = None
    name: dict[str, str] | None = None
    source: str | None = None
    kind: str | None = None
    summary: str | None = None
    cost: dict[str, Any] | None = None
    typical: str | None = None
    status: str | None = None
    essential: bool | None = None
    beta: bool | None = None
    description: str | None = None
    inputs: list[dict[str, Any]] | None = None
    output: dict[str, Any] | None = None
    examples: list[dict[str, Any]] | None = None
    input_schema: dict[str, Any] | None = None


@dataclass(kw_only=True, slots=True)
class ToolList(Model):
    """The answer to `tools.find`: the `tools` on this page, best match first, the `total` that
    match, and `next_cursor` for the next page (None on the last page)."""

    tools: list[ToolSummary] | None = None
    total: int | None = None
    next_cursor: str | None = None
    counts: dict[str, Any] | None = None

    _nested: ClassVar[dict[str, type[Model]]] = {"tools": ToolSummary}


@dataclass(kw_only=True, slots=True)
class ToolEstimate(Model):
    """The answer to `tools.estimate`, with the estimate in `data`: `data["text"]` says the price in
    words (`1 cr`). A tool priced by what the run returns gives `data["rule"]`; a tool priced by its
    inputs gives `data["min"]` and `data["max"]`."""

    tool: str | None = None
    request_id: str | None = None
    data: dict[str, Any] | None = None


@dataclass(kw_only=True, slots=True)
class ToolRun(Response):
    """The answer to `tools.run`, the same shape for every tool: the `rows` it found (a tool that
    returns rows), the rest of its answer in `data`, `usage["credits"]`, `took_ms` and the
    `request_id` to quote when you report a problem."""

    tool: str | None = None
    request_id: str | None = None
    took_ms: int | None = None
    usage: dict[str, Any] | None = None
    rows: list[dict[str, Any]] | None = None
    data: Any = None
