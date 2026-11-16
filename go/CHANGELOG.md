# Changelog

## 1.0.0

The first Go SDK, for the current Crawl4AI Cloud API.

- `Client`, with `Scrape`, `ScrapeBatch`, `StartScrapeJob`, `GetScrapeJob`, `WaitScrapeJob`,
  `GetScrapeJobResults`, `RetryScrapeJob`, `Search`, `Serp`, `Answer`, `Extract`.
- Typed results with the API's field names, the call's cost in `Cost`, `Balance` and
  `AllowanceLeft`, and the whole answer in `Raw`.
- One `*Error` type; its kind is tested with `errors.Is` (`ErrPaymentRequired`, `ErrBlocked`, ...).
- Retries on 429 and 503 with backoff and `Retry-After`; a 120 s timeout; your context ends a call.
- Streams (`ScrapeBatch`, `GetScrapeJobResults`) are Go 1.23 iterators.
- No dependencies.
