# The API contract

`openapi.yaml` describes the public Crawl4AI Cloud API: every endpoint, request, response and error
the SDKs call. Every SDK follows it. Source of truth for its content: https://crawl4ai.com/docs/ and
https://crawl4ai.com/llms.txt. When this file and the docs disagree, the docs win: fix this file.

It covers `/scrape`, `/scrape/batch`, `/scrape/jobs`, `/search`, `/serp`, `/answer` and `/extract` today.
A new endpoint is added here first, then to each SDK.

A field whose values the server may grow (`format`, `engine`, a job's `status`) is an `OpenString`:
the docs list today's values, and a client must accept any other string too.

Check it before a pull request:

```bash
npx @redocly/cli lint spec/openapi.yaml
```
