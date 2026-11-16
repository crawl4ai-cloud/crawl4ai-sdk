# Changelog

## 2.0.0

A new SDK for the current Crawl4AI Cloud API. Not compatible with 1.x; see "Moving from 1.x" in the README.

- `Crawl4AI`, with `scrape`, `scrapeBatch`, `startScrapeJob`, `getScrapeJob`, `waitScrapeJob`,
  `getScrapeJobResults`, `retryScrapeJob`, `search`, `serp`, `answer`, `extract`.
- Typed results with the API's field names, and the call's cost in `cost`, `balance` and `allowance_left`.
- One error class per status, each with the server's `code`, `message` and `actions`.
- Retries on 429 and 503 with backoff and `Retry-After`; a 120 s timeout.
- No dependencies. Node 20.19+, an ES module that CommonJS can `require`.
