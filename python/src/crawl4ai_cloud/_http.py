"""What the sync and the async client share: the key, the headers, when to retry, and how an
error answer becomes an exception."""

from __future__ import annotations

import json
import os
import random
from typing import Any
from urllib.parse import quote

import httpx

from ._version import __version__
from .errors import (
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
    `_KEY_ENV_VARS` that is set; with neither it raises AuthenticationError."""
    key = api_key or next((os.environ[n] for n in _KEY_ENV_VARS if os.environ.get(n)), None)
    if not key:
        raise AuthenticationError("No API key: pass api_key=... or set CRAWL4AI_API_KEY.")
    return {"Authorization": f"Bearer {key}", "User-Agent": f"crawl4ai-cloud-python/{__version__}"}


def should_retry(status: int, safe: bool) -> bool:
    """True when a request that got `status` is worth sending again.

    429 and 503 mean the server did not start the work, so every request retries them.
    500 and 504 retry only when `safe` (sending the request twice cannot run the work twice).
    """
    return status in (429, 503) or (safe and status in (500, 504))


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
    `{"ok": false, "reason": code}`, and some errors send plain text or nothing.
    """
    status = response.status_code
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        body = {}
    code = body.get("error") or body.get("reason")
    code = None if code is None else str(code)
    message = body.get("message") or code or response.text.strip()[:500] or f"HTTP {status}"
    error_class = _ERROR_BY_STATUS.get(status) or (ServerError if status >= 500 else Crawl4AIError)
    return error_class(message, status=status, code=code, actions=body.get("actions"))


def body(**fields: Any) -> dict[str, Any]:
    """Returns the fields that are not None: the request leaves out what the caller did not set."""
    return {k: v for k, v in fields.items() if v is not None}


def flag(value: bool | None) -> int | None:
    """Turns a bool into the 0 or 1 the API's query parameters take; None stays None."""
    return None if value is None else int(value)


def schema_param(schema: dict[str, Any] | None) -> str | None:
    """Turns a JSON Schema into the JSON text `/answer` takes in its query string."""
    return None if schema is None else json.dumps(schema, separators=(",", ":"))


def job_path(job_id: str, tail: str = "") -> str:
    """Returns `/scrape/jobs/<job_id><tail>`, with the id escaped for a URL.
    Raises ValueError for an empty id or `.` / `..`, which a URL reads as a folder step."""
    if job_id in ("", ".", ".."):
        raise ValueError(f"Not a job id: {job_id!r}")
    return f"/scrape/jobs/{quote(job_id, safe='')}{tail}"
