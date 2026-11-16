# Crawl4AI Cloud, Node.js and TypeScript SDK

The official Node.js client for the [Crawl4AI Cloud API](https://crawl4ai.com/docs/): web pages to
Markdown and JSON, web search, Google results and answers. Node 20.19+, TypeScript types included,
no dependencies.

```bash
npm install crawl4ai-cloud
```

```ts
import { Crawl4AI } from "crawl4ai-cloud";

const client = new Crawl4AI(); // the key comes from CRAWL4AI_API_KEY
const page = await client.scrape("https://example.com");
console.log(page.markdown);
```

Get a key at https://crawl4ai.com. Pass it as `new Crawl4AI({ apiKey: "sk_live_..." })` or set
`CRAWL4AI_API_KEY`. Never commit a key.

The package is an ES module. From CommonJS, `require("crawl4ai-cloud")` works on Node 20.19+ and 22.12+.

## What you can call

| Method | What it does |
|---|---|
| `scrape(url)` | One page to Markdown and/or HTML |
| `scrapeBatch(urls)` | Up to 50 pages; yields each one as soon as it is ready |
| `startScrapeJob(urls)` | Up to 10,000 pages in the background; returns a `job_id` |
| `waitScrapeJob(jobId)` | Waits until the job is done |
| `getScrapeJobResults(jobId)` | Yields every page of the job |
| `getScrapeJob(jobId)` | The job's status, counts and cost |
| `retryScrapeJob(jobId)` | Runs the job's failed URLs again |
| `search(q)` | Web search results |
| `serp(q)` | Google's results page as data (beta) |
| `answer(q)` | A direct answer with sources (experimental) |
| `extract(url, { instruction })` | Structured JSON from a page |

Every method has a doc comment with an example; your editor shows it.

### Many pages

```ts
// up to 50: results stream back as each page finishes
for await (const item of client.scrapeBatch(["https://example.com", "https://example.org"], { format: "md" })) {
  console.log(item.url, item.ok ? item.result?.markdown?.slice(0, 80) : item.error);
}

// up to 10,000: a background job
const job = await client.startScrapeJob(urls, { format: "md" });
await client.waitScrapeJob(job.job_id);
for await (const item of client.getScrapeJobResults(job.job_id)) {
  console.log(item.url, item.ok);
}
```

### Search, Google results, answers, extraction

```ts
for (const result of (await client.search("rust web crawler")).results) {
  console.log(result.title, result.url);
}

for (const result of (await client.serp("best crm software", { country: "us", num: 20 })).results) {
  console.log(result.position, result.domain);
}

const schema = { type: "object", properties: { name: { type: "string" } } };
const result = await client.answer("Who founded Python?", { schema });
if (result.answered) console.log(JSON.parse(result.answer!.text));

const { data } = await client.extract("https://news.ycombinator.com", { instruction: "the top 3 story titles" });
const mine = await client.extract({ content: "<p>Price: $5</p>", instruction: "the price" });
```

## Results

Every result is the server's JSON answer, typed, with the API's own field names (`page.markdown`,
`job.job_id`, `page.text_len`), the same names as in every Crawl4AI SDK. A field the server did not
send is `undefined`, and a field the server adds later is still there. Every result also carries
what the call cost: `cost`, `balance` and `allowance_left`, in credits (1 credit = $0.001).

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

```ts
import { BlockedError, PaymentRequiredError } from "crawl4ai-cloud";

try {
  const page = await client.scrape("https://example.com");
} catch (e) {
  if (e instanceof PaymentRequiredError) console.log(e.message, e.actions?.subscribe);
  else if (e instanceof BlockedError) console.log("the site refused:", e.code);
  else throw e;
}
```

## Retries and timeouts

A call that gets 429 or 503 (busy) is sent again up to 3 times, waiting longer each time and
honouring `Retry-After`. A call that cannot run twice, like starting a job, is never retried after a
500. Each call waits up to 120 s for an answer, because a page that needs a real browser can take
90 s; a streamed answer may take longer, as long as each part comes within that time.

```ts
const client = new Crawl4AI({ timeout: 60_000, maxRetries: 5 }); // milliseconds
```

Pass `fetch` to send the calls through your own function (for a proxy, say).

## Moving from 1.x

2.0 is a new SDK for the current API; the 1.x `AsyncWebCrawler` is gone, along with the `/v1` API it
called (shut down on 2026-11-06). `screenshot`, `scan`, `map` and `enrich` are not part of the
current API.

| 1.x | 2.0 |
|---|---|
| `new AsyncWebCrawler({ apiKey })` | `new Crawl4AI({ apiKey })` |
| `scrape(url, { include: [...] })` | `scrape(url, { parse: { links: true, ... } })` |
| `scrapeMany(urls)` | `scrapeBatch(urls)` or `startScrapeJob(urls)` |
| `getScrapeJob(job.jobId)` | `getScrapeJob(job.job_id)` |
| `extract(url, { query })` | `extract(url, { instruction })` |
| `search(query, { country })` | `search(q)`, or `serp(q, { country })` for Google's page |

## Develop

```bash
npm install
npm test                                       # build, type-check, unit tests against a fake fetch
CRAWL4AI_API_KEY=sk_live_... npm test          # also the live tests; they spend a few credits
```

Node 22.18+ runs the TypeScript tests directly.
