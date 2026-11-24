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
- `client.Tools`, the Toolkit: `Find`, `Get`, `Estimate`, `Run` and `Batch` call every tool at
  `/tools` the same way. A run or a batch is never sent twice after a 500 or a lost connection; a
  503 `tool_failing` is not retried. `Find` and `Get` work without a key, so `NewClient` no longer
  fails without one; every other call returns an `ErrAuthentication` error before it is sent.
- `Error.Body` keeps the whole error answer (`did_you_mean` on a 404 `tool_not_found`), and the
  message of a 422 `invalid_input` names the problem.
