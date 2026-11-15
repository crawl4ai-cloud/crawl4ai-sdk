# Crawl4AI Cloud, Go SDK

The official Go client for the [Crawl4AI Cloud API](https://crawl4ai.com/docs/): web pages to
Markdown and JSON, web search, Google results and answers. Go 1.23+, no dependencies.

```bash
go get github.com/crawl4ai-cloud/crawl4ai-sdk/go
```

```go
import crawl4ai "github.com/crawl4ai-cloud/crawl4ai-sdk/go"

client, err := crawl4ai.NewClient() // the key comes from CRAWL4AI_API_KEY
if err != nil {
	log.Fatal(err)
}
page, err := client.Scrape(ctx, "https://example.com", nil)
if err != nil {
	log.Fatal(err)
}
fmt.Println(page.Markdown)
```

Get a key at https://crawl4ai.com. Pass it as `crawl4ai.NewClient(crawl4ai.WithAPIKey("sk_live_..."))`
or set `CRAWL4AI_API_KEY`. Never commit a key.

## What you can call

Every method takes a `context.Context` first, and its options as a pointer you may leave `nil`.

| Method | What it does |
|---|---|
| `Scrape(ctx, url, opts)` | One page to Markdown and/or HTML |
| `ScrapeBatch(ctx, urls, opts)` | Up to 50 pages; yields each one as soon as it is ready |
| `StartScrapeJob(ctx, urls, opts)` | Up to 10,000 pages in the background; returns a `JobID` |
| `WaitScrapeJob(ctx, jobID, opts)` | Waits until the job is done |
| `GetScrapeJobResults(ctx, jobID)` | Yields every page of the job |
| `GetScrapeJob(ctx, jobID, opts)` | The job's status, counts and cost |
| `RetryScrapeJob(ctx, jobID)` | Runs the job's failed URLs again |
| `Search(ctx, q, opts)` | Web search results |
| `Serp(ctx, q, opts)` | Google's results page as data (beta) |
| `Answer(ctx, q, opts)` | A direct answer with sources (experimental) |
| `Extract(ctx, opts)` | Structured JSON from a page or your own text |

Every method has a doc comment with an example (`go doc crawl4ai.Client.Scrape`).

### Many pages

`ScrapeBatch` and `GetScrapeJobResults` return an iterator: range over it, and stop when you like.

```go
// up to 50: results stream back as each page finishes
for item, err := range client.ScrapeBatch(ctx, []string{"https://example.com", "https://example.org"}, nil) {
	if err != nil {
		return err
	}
	fmt.Println(item.URL, item.OK)
}

// up to 10,000: a background job
job, err := client.StartScrapeJob(ctx, urls, &crawl4ai.ScrapeOptions{Format: "md"})
if err != nil {
	return err
}
if _, err := client.WaitScrapeJob(ctx, job.JobID, &crawl4ai.WaitOptions{Timeout: 10 * time.Minute}); err != nil {
	return err
}
for item, err := range client.GetScrapeJobResults(ctx, job.JobID) {
	if err != nil {
		return err
	}
	fmt.Println(item.URL, item.OK)
}
```

### Search, Google results, answers, extraction

```go
res, err := client.Search(ctx, "rust web crawler", nil)

serp, err := client.Serp(ctx, "best crm software", &crawl4ai.SerpOptions{Country: "us", Num: 20})
panel := serp.Block("knowledge_panel") // any block Google showed, as JSON

schema := map[string]any{"type": "object", "properties": map[string]any{"name": map[string]any{"type": "string"}}}
ans, err := client.Answer(ctx, "Who founded Python?", &crawl4ai.AnswerOptions{Schema: schema})
// ans.Answer.Text is JSON in the schema's shape

ext, err := client.Extract(ctx, &crawl4ai.ExtractOptions{URL: "https://news.ycombinator.com", Instruction: "the top 3 story titles"})
// ext.Data is JSON: unmarshal it into your own type
```

## Results

Every result is a struct with the API's own field names in its JSON tags (`JobID` is `job_id`,
`TextLen` is `text_len`), the same names as in every Crawl4AI SDK. Every answer to a call also has
`Cost`, `Balance` and `AllowanceLeft` (credits, 1 credit = $0.001; `nil` when the server did not
send them) and `Raw`, the whole answer as JSON, so a field the server adds later is never lost.

## Errors

Every error is a `*crawl4ai.Error` with `Status`, `Code`, `Message` (show it to people as it is) and
`Actions` (links that fix the problem). Test its kind with `errors.Is`:

| Kind | When |
|---|---|
| `ErrBadRequest` | 400 / 422: a field is wrong |
| `ErrAuthentication` | 401: no key, or a key that is not valid |
| `ErrPaymentRequired` | 402: out of credit (`Code`: `no_credit`, `plan_cap`, `spend_cap`, `plan_needed`) |
| `ErrBlocked` | 403: the site refused every attempt (`Code`: `blocked`, `login-wall`) |
| `ErrNotFound` | 404: no such job, or not open to your account |
| `ErrRateLimit` | 429: over your plan's pace, after every retry |
| `ErrServer` | 5xx: the service or the site failed (`Code`: `busy`, `no-answer`, ...) |
| `ErrConnection`, `ErrTimeout` | No answer came back (a timeout is also an `ErrConnection`) |

```go
page, err := client.Scrape(ctx, "https://example.com", nil)
var e *crawl4ai.Error
switch {
case errors.Is(err, crawl4ai.ErrPaymentRequired) && errors.As(err, &e):
	fmt.Println(e.Message, e.Actions["subscribe"])
case errors.Is(err, crawl4ai.ErrBlocked) && errors.As(err, &e):
	fmt.Println("the site refused:", e.Code)
case err != nil:
	return err
}
```

When your own context ends, the error wraps its cause: `errors.Is(err, context.Canceled)`.

## Retries and timeouts

A call that gets 429 or 503 (busy) is sent again up to 3 times, waiting longer each time and
honouring `Retry-After`. A call that cannot run twice, like starting a job, is never retried after a
500. Each call waits up to 120 s for an answer, because a page that needs a real browser can take
90 s; a streamed answer may take longer, as long as each part comes within that time. Your context's
deadline, when it has one, also ends the call.

```go
client, err := crawl4ai.NewClient(crawl4ai.WithTimeout(60*time.Second), crawl4ai.WithMaxRetries(5))
```

`WithHTTPClient` sends the calls through your own `*http.Client` (for a proxy, say).

## Develop

```bash
go test ./...                                  # unit tests against a fake server
CRAWL4AI_API_KEY=sk_live_... go test ./...     # also the live tests; they spend a few credits
```

Releases are tagged `go/vX.Y.Z`.
