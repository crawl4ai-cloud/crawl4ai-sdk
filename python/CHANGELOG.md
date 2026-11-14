# Changelog

## 2.0.0

A new SDK for the current Crawl4AI Cloud API. Not compatible with 1.x; see "Moving from 1.x" in the README.

- `Crawl4AI` and `AsyncCrawl4AI`, with `scrape`, `scrape_batch`, `start_scrape_job`, `get_scrape_job`,
  `wait_scrape_job`, `get_scrape_job_results`, `retry_scrape_job`, `search`, `serp`, `answer`, `extract`.
- Typed results that keep the full answer in `.raw` and the call's cost in `.cost` and `.balance`.
- One error per status, each with the server's `code`, `message` and `actions`.
- Retries on 429 and 503 with backoff and `Retry-After`; a 120 s timeout.
- One dependency: `httpx`. Python 3.10+.
