# Changelog

## 2.0.0

A new SDK for the current Crawl4AI Cloud API. Not compatible with 1.x; see "Moving from 1.x" in the README.

- `Crawl4AI` and `AsyncCrawl4AI`, with `scrape`, `scrape_batch`, `start_scrape_job`, `get_scrape_job`,
  `wait_scrape_job`, `get_scrape_job_results`, `retry_scrape_job`, `search`, `serp`, `answer`, `extract`.
- Typed results that keep the full answer in `.raw` and the call's cost in `.cost` and `.balance`.
- One error per status, each with the server's `code`, `message` and `actions`.
- Retries on 429 and 503 with backoff and `Retry-After`; a 120 s timeout.
- One dependency: `httpx`. Python 3.10+.
- `client.tools`, the Toolkit: `find`, `get`, `estimate` and `run` call every tool at `/tools` the same way.
  A run is never sent twice after a 500 or a lost connection; a 503 `tool_failing` is not retried.
  `find` and `get` work without a key; every other call still raises before it is sent.
  `batch` runs a tool on many inputs as one job, read with the scrape job methods; never sent twice.
- Errors keep the whole error answer in `.body` (`details`, `did_you_mean`).
- A cost header that is not a number is None instead of failing a call that was already charged.
- `search(q, deep=True)` reads the top result pages into each result's `markdown`.
