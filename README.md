# Crawl4AI Cloud SDKs

Official client libraries for the [Crawl4AI Cloud API](https://api.crawl4ai.com/docs):
`/scrape` a page to Markdown, `/extract` it to JSON, `/search` the web, `/serp` for Google's results
as data, `/answer` a question with sources, and batches of many URLs. One key, three regions,
routed to the nearest one.

| Language | Folder | Package | Install |
|---|---|---|---|
| Python | [`python/`](python/) | `crawl4ai-cloud-sdk` (PyPI) | `pip install crawl4ai-cloud-sdk` |
| Node / TypeScript | [`node/`](node/) | `crawl4ai-cloud` (npm) | `npm install crawl4ai-cloud` |
| Go | [`go/`](go/) | `github.com/crawl4ai-cloud/crawl4ai-sdk/go` | `go get github.com/crawl4ai-cloud/crawl4ai-sdk/go` |
| Rust | [`rust/`](rust/) | `crawl4ai-cloud` (crates.io) | `cargo add crawl4ai-cloud` |

The new SDKs are in progress. Until a folder has its first release, use the HTTP API directly
(docs: https://api.crawl4ai.com/docs) or the MCP server (https://crawl4ai.com/llms.txt).

## Your API key

Get a key at https://crawl4ai.com. Every SDK reads it from the `CRAWL4AI_API_KEY` environment
variable when you do not pass one. Never commit a key to a repository.

## How this repository works

- [`spec/`](spec/) holds the API contract (`openapi.yaml`). Every SDK follows it; a change to the API starts there.
- Each language folder is its own package with its own tests, changelog and releases.
- Releases are tagged per package: `python-v1.3.0`, `node-v1.5.0`, `go/v1.0.0`, `rust-v0.1.0`.
- [`docs/`](docs/) is written for people and for AI coding agents.

## Issues and contributions

Found a bug or want a feature? [Open an issue](../../issues/new/choose).
Security problem? Do not open an issue; see [SECURITY.md](SECURITY.md).
Want to help? Read [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
