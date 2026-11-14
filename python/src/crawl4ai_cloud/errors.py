"""The exceptions the SDK raises. Catch `Crawl4AIError` to catch them all."""

from __future__ import annotations

from typing import Any


class Crawl4AIError(Exception):
    """Every error the SDK raises.

    `status` is the HTTP status (None when no answer came back), `code` the server's short code
    (`no_credit`, `blocked`, ...), `message` text you can show to people as it is, and `actions`
    the server's links that fix the problem (for example `subscribe`).
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        actions: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.actions = actions


class BadRequestError(Crawl4AIError):
    """400 or 422: a field is wrong. `message` says which."""


class AuthenticationError(Crawl4AIError):
    """401: the API key is missing or not valid."""


class PaymentRequiredError(Crawl4AIError):
    """402: out of credit. `code` is `no_credit`, `plan_cap`, `spend_cap` or `plan_needed`."""


class BlockedError(Crawl4AIError):
    """403 from `/scrape`: the site refused every attempt. `code` is `blocked` or `login-wall`."""


class NotFoundError(Crawl4AIError):
    """404: no such job, or `not_available` (not open to this account)."""


class RateLimitError(Crawl4AIError):
    """429: over the plan's requests a minute or calls at a time, after every retry."""


class ServerError(Crawl4AIError):
    """5xx: the service or the site failed. `code` says why, for example `busy` or `no-answer`."""


class APIConnectionError(Crawl4AIError):
    """No answer came back: the network failed before the server replied."""


class APITimeoutError(APIConnectionError):
    """No answer within the timeout, or a job not done before `wait_scrape_job`'s timeout."""
