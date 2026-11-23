"""What the sync and the async client share: the key, the headers, when to retry, and how an
error answer becomes an exception."""

from __future__ import annotations

import json
import os
import random
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import quote

import httpx

from ._version import __version__
from .errors import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    BlockedError,
    Crawl4AIError,
    NotFoundError,
    PaymentRequiredError,
    RateLimitError,
    ServerError,
)

BASE_URL = "https://api.crawl4ai.com"
TIMEOUT = 120.0  # the docs' advice: a page that needs a real browser can take 90 s
MAX_RETRIES = 3

# CRAWL4AI_KEY is the name llms.txt gives agents; CRAWL4AI_API_KEY is the SDKs' name and wins.
_KEY_ENV_VARS = ("CRAWL4AI_API_KEY", "CRAWL4AI_KEY")

_ERROR_BY_STATUS: dict[int, type[Crawl4AIError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    402: PaymentRequiredError,
    403: BlockedError,
    404: NotFoundError,
    422: BadRequestError,
    429: RateLimitError,
}


def headers(api_key: str | None) -> dict[str, str]:
    """Returns the headers of every request. The key is `api_key`, else the first env var of
    `_KEY_ENV_VARS` that is set; with neither it raises AuthenticationError. A key with a character
    a header cannot carry raises too, without the key: httpx's own error would quote it whole."""
    key = (api_key or next((os.environ[n] for n in _KEY_ENV_VARS if os.environ.get(n)), "")).strip()
    if not key:
        raise AuthenticationError("No API key: pass api_key=... or set CRAWL4AI_API_KEY.")
    if not re.fullmatch(r"[\x21-\x7e]+", key):
        raise AuthenticationError("The API key has a character that is not allowed.")
    return {"Authorization": f"Bearer {key}", "User-Agent": f"crawl4ai-cloud-python/{__version__}"}


def should_retry(error: Crawl4AIError, safe: bool) -> bool:
    """True when a request that got `error` is worth sending again.

    429 and 503 mean the server did not start the work, so every request retries them, except a
    503 `tool_failing`: the tool's daily check is failing, so the same call fails again.
    500 and 504 retry only when `safe` (sending the request twice cannot run the work twice).
    """
    if error.code == "tool_failing":
        return False
    return error.status in (429, 503) or (safe and error.status in (500, 504))


def retry_delay(attempt: int, response: httpx.Response | None = None) -> float:
    """Seconds to wait before retry number `attempt` (0 = the first retry): the server's
    `Retry-After` when it sends one (at most 60 s), else 0.5 s doubled each time, at most 8 s,
    with random jitter so many clients do not retry at the same moment."""
    retry_after = response.headers.get("retry-after", "") if response is not None else ""
    if retry_after.isdigit():
        return min(float(retry_after), 60.0)
    return min(0.5 * 2.0**attempt, 8.0) * random.uniform(0.5, 1.0)


def error_from(response: httpx.Response) -> Crawl4AIError:
    """Builds the exception for an error answer; the body must already be read.

    The server sends `{"error": code, "message": ..., "actions": ...}`, `/scrape` sends
    `{"ok": false, "reason": code}`, `/tools` adds `details` or `did_you_mean`, and some errors
    send plain text or nothing.
    """
    status = response.status_code
    try:
        body = response.json()
    except ValueError:
        body = None
    text = "" if isinstance(body, dict) else response.text.strip()[:500]
    if not isinstance(body, dict):
        body = {}
    code = body.get("error") or body.get("reason")
    code = None if code is None else str(code)
    # /tools says what is wrong in `details`: [{"input": "url", "problem": "url is required"}]
    details = body.get("details")
    problems = [str(d["problem"]) for d in details if isinstance(d, dict) and d.get("problem")] if isinstance(details, list) else []
    detail = f"{code}: {'; '.join(problems)}" if code and problems else code
    message = body.get("message") or detail or text or f"HTTP {status}"
    error_class = _ERROR_BY_STATUS.get(status) or (ServerError if status >= 500 else Crawl4AIError)
    return error_class(message, status=status, code=code, actions=body.get("actions"), body=body or None)


@contextmanager
def reading(path: str) -> Iterator[None]:
    """Turns a failure while an answer's body comes in into APITimeoutError or APIConnectionError.
    It is never retried: the server answered, so it may already have done the work."""
    try:
        yield
    except httpx.TimeoutException as e:
        raise APITimeoutError(f"{path}: the answer stopped coming in time: {e}") from e
    except httpx.TransportError as e:
        raise APIConnectionError(f"{path}: the answer stopped: {e}") from e


def parse(text: bytes, path: str) -> Any:
    """Reads JSON. A body that is not JSON (a proxy's HTML page, say) raises APIConnectionError."""
    try:
        return json.loads(text)
    except ValueError as e:
        raise APIConnectionError(f"{path}: the answer is not JSON: {text[:100].decode(errors='replace')}") from e


def body(**fields: Any) -> dict[str, Any]:
    """Returns the fields that are not None: the request leaves out what the caller did not set."""
    return {k: v for k, v in fields.items() if v is not None}


def flag(value: bool | None) -> int | None:
    """Turns a bool into the 0 or 1 the API's query parameters take; None stays None."""
    return None if value is None else int(value)


def schema_param(schema: dict[str, Any] | None) -> str | None:
    """Turns a JSON Schema into the JSON text `/answer` takes in its query string."""
    return None if schema is None else json.dumps(schema, separators=(",", ":"))


def tool_path(tool_id: str, tail: str = "") -> str:
    """Returns `/tools/<tool_id><tail>`, with the id escaped for a URL.
    Raises ValueError for an empty id or `.` / `..`, which a URL reads as a folder step."""
    if tool_id in ("", ".", ".."):
        raise ValueError(f"Not a tool id: {tool_id!r}")
    return f"/tools/{quote(tool_id, safe='')}{tail}"


def job_path(job_id: str, tail: str = "") -> str:
    """Returns `/scrape/jobs/<job_id><tail>`, with the id escaped for a URL.
    Raises ValueError for an empty id or `.` / `..`, which a URL reads as a folder step."""
    if job_id in ("", ".", ".."):
        raise ValueError(f"Not a job id: {job_id!r}")
    return f"/scrape/jobs/{quote(job_id, safe='')}{tail}"
