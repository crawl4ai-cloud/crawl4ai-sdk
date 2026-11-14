"""The official Python client for the Crawl4AI Cloud API.

Example:
    from crawl4ai_cloud import Crawl4AI

    page = Crawl4AI().scrape("https://example.com")   # the key comes from CRAWL4AI_API_KEY
    print(page.markdown)
"""

from ._client import AsyncCrawl4AI, Crawl4AI
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
from .types import (
    Answer,
    AnswerResult,
    ExtractResult,
    Link,
    ScrapeBatchItem,
    ScrapeJob,
    ScrapeJobItem,
    ScrapeJobRetry,
    ScrapeResult,
    SearchItem,
    SearchResult,
    SerpItem,
    SerpResult,
)

__all__ = [
    "APIConnectionError",
    "APITimeoutError",
    "Answer",
    "AnswerResult",
    "AsyncCrawl4AI",
    "AuthenticationError",
    "BadRequestError",
    "BlockedError",
    "Crawl4AI",
    "Crawl4AIError",
    "ExtractResult",
    "Link",
    "NotFoundError",
    "PaymentRequiredError",
    "RateLimitError",
    "ScrapeBatchItem",
    "ScrapeJob",
    "ScrapeJobItem",
    "ScrapeJobRetry",
    "ScrapeResult",
    "SearchItem",
    "SearchResult",
    "SerpItem",
    "SerpResult",
    "ServerError",
    "__version__",
]
