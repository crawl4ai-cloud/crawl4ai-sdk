# Changelog

## 2.0.0

A new SDK for the current Crawl4AI Cloud API. Not compatible with 1.x; see "Moving from 1.x" in the README.

- `Crawl4AI`, with `scrape`, `scrapeBatch`, `startScrapeJob`, `getScrapeJob`, `waitScrapeJob`,
  `getScrapeJobResults`, `retryScrapeJob`, `search`, `serp`, `answer`, `extract`.
- Typed results with the API's field names, and the call's cost in `cost`, `balance` and `allowance_left`.
- One error class per status, each with the server's `code`, `message` and `actions`.
- Retries on 429 and 503 with backoff and `Retry-After`; a 120 s timeout.
- No dependencies. Node 20.19+, an ES module that CommonJS can `require`.
- `client.tools`, the Toolkit: `find`, `get`, `estimate` and `run` call every tool at `/tools` the same way.
  A run is never sent twice after a 500 or a lost connection; a 503 `tool_failing` is not retried.
- Errors keep the whole error answer in `.body` (`details`, `did_you_mean`).
- `scrape`'s option is `bypassCache`, in the SDK's camelCase like every other option.
- Works in the browser: the default `fetch` is no longer called as a method of the client.
- A cost header that is missing or not a number is undefined, and never lets a body field of the same name through.
- `search(q, { deep: true })` reads the top result pages into each result's `markdown`.
