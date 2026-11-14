# Crawl4AI Cloud, Python SDK

The official Python client for the [Crawl4AI Cloud API](https://crawl4ai.com/docs/): web pages to
Markdown and JSON, web search, Google results and answers. Python 3.10+, one dependency (`httpx`).

```bash
pip install crawl4ai-cloud-sdk
```

```python
from crawl4ai_cloud import Crawl4AI

client = Crawl4AI()  # the key comes from CRAWL4AI_API_KEY
page = client.scrape("https://example.com")
print(page.markdown)
```

Get a key at https://crawl4ai.com. Pass it as `Crawl4AI(api_key="sk_live_...")` or set
`CRAWL4AI_API_KEY`. Never commit a key.

## What you can call

| Method | What it does |
|---|---|
| `scrape(url)` | One page to Markdown and/or HTML |
| `scrape_batch(urls)` | Up to 50 pages; yields each one as soon as it is ready |
| `start_scrape_job(urls)` | Up to 10,000 pages in the background; returns a `job_id` |
| `wait_scrape_job(job_id)` | Waits until the job is done |
| `get_scrape_job_results(job_id)` | Yields every page of the job |
| `get_scrape_job(job_id)` | The job's status, counts and cost |
| `retry_scrape_job(job_id)` | Runs the job's failed URLs again |
| `search(q)` | Web search results |
| `serp(q)` | Google's results page as data (beta) |
| `answer(q)` | A direct answer with sources (experimental) |
| `extract(url, instruction=...)` | Structured JSON from a page |

Every method has a doc comment with an example: `help(Crawl4AI.scrape)`.

### Many pages

```python
# up to 50: results stream back as each page finishes
for item in client.scrape_batch(["https://example.com", "https://example.org"], format="md"):
    print(item.url, item.result.markdown[:80] if item.ok else item.error)

# up to 10,000: a background job
job = client.start_scrape_job(urls, format="md")
client.wait_scrape_job(job.job_id)
for item in client.get_scrape_job_results(job.job_id):
    print(item.url, item.ok)
```

### Search, Google results, answers, extraction

```python
for result in client.search("rust web crawler").results:
    print(result.title, result.url)

for result in client.serp("best crm software", country="us", num=20).results:
    print(result.position, result.domain)

result = client.answer("Who founded Python?", schema={"type": "object", "properties": {"name": {"type": "string"}}})
if result.answered:
    print(result.answer.text)  # JSON text in the schema's shape

data = client.extract("https://news.ycombinator.com", instruction="the top 3 story titles").data
```

### Async

`AsyncCrawl4AI` has the same methods. `scrape_batch` and `get_scrape_job_results` are async iterators.

```python
import asyncio
from crawl4ai_cloud import AsyncCrawl4AI

async def main():
    async with AsyncCrawl4AI() as client:
        pages = await asyncio.gather(*(client.scrape(u) for u in ["https://example.com", "https://example.org"]))
        print([p.text_len for p in pages])

asyncio.run(main())
```

## Results

Every result is a dataclass with the API's field names (`page.markdown`, `job.status`). A field the
server did not send is `None`. The full JSON answer is in `.raw`, so a field the server adds later is
never lost. Every result also carries what the call cost: `.cost`, `.balance` and `.allowance_left`,
in credits (1 credit = $0.001).

## Errors

Every error is a `Crawl4AIError` with `status`, `code`, `message` (show it to people as it is) and
`actions` (links that fix the problem).

| Error | When |
|---|---|
| `BadRequestError` | 400 / 422: a field is wrong |
| `AuthenticationError` | 401: no key, or a key that is not valid |
| `PaymentRequiredError` | 402: out of credit (`code`: `no_credit`, `plan_cap`, `spend_cap`, `plan_needed`) |
| `BlockedError` | 403: the site refused every attempt (`code`: `blocked`, `login-wall`) |
| `NotFoundError` | 404: no such job, or not open to your account |
| `RateLimitError` | 429: over your plan's pace, after every retry |
| `ServerError` | 5xx: the service or the site failed (`code`: `busy`, `no-answer`, ...) |
| `APIConnectionError`, `APITimeoutError` | No answer came back |

```python
from crawl4ai_cloud import BlockedError, PaymentRequiredError

try:
    page = client.scrape("https://example.com")
except PaymentRequiredError as e:
    print(e.message, (e.actions or {}).get("subscribe"))
except BlockedError as e:
    print("the site refused:", e.code)
```

## Retries and timeouts

A call that gets 429 or 503 (busy) is sent again up to 3 times, waiting longer each time and
honouring `Retry-After`. A call that cannot run twice, like starting a job, is never retried after a
500. Each call waits up to 120 s, because a page that needs a real browser can take 90 s.

```python
client = Crawl4AI(timeout=60, max_retries=5)
```

## Moving from 1.x

2.0 is a new SDK for the current API; the 1.x `AsyncWebCrawler`, `run` and `CrawlerRunConfig`
are gone, along with the `/v1` API they called (shut down on 2026-11-06).

| 1.x | 2.0 |
|---|---|
| `AsyncWebCrawler(api_key=...)` | `Crawl4AI(api_key=...)` or `AsyncCrawl4AI(...)` |
| `await crawler.run(url)` | `client.scrape(url)` |
| `await crawler.run_many(urls)` | `client.scrape_batch(urls)` or `client.start_scrape_job(urls)` |
| `extract(url, query=...)` | `extract(url, instruction=...)` |
| `search(query, ...)` | `search(q, rich=...)` |

## Develop

```bash
pip install -e ".[dev]"
pytest                                   # unit tests against a fake server
CRAWL4AI_API_KEY=sk_live_... pytest tests/test_live.py   # live tests; they spend a few credits
```
