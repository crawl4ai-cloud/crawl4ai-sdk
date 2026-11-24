// Package crawl4ai is the Go client for the Crawl4AI Cloud API (https://crawl4ai.com/docs/): web
// pages to Markdown and JSON, web search, Google results and answers.
//
//	client, err := crawl4ai.NewClient() // the key comes from CRAWL4AI_API_KEY
//	if err != nil {
//		log.Fatal(err)
//	}
//	page, err := client.Scrape(context.Background(), "https://example.com", nil)
//	if err != nil {
//		log.Fatal(err)
//	}
//	fmt.Println(page.Markdown)
//
// Every method sends its call through Client.open, which adds the headers, retries what is worth
// retrying and turns an error answer into an *Error.
package crawl4ai

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"iter"
	"math/rand/v2"
	"net"
	"net/http"
	"net/url"
	"os"
	"slices"
	"strconv"
	"strings"
	"sync/atomic"
	"time"
)

const (
	Version           = "1.0.0"
	BaseURL           = "https://api.crawl4ai.com"
	DefaultTimeout    = 120 * time.Second // the docs' advice: a page that needs a real browser can take 90 s
	DefaultMaxRetries = 3
)

// CRAWL4AI_KEY is the name llms.txt gives agents; CRAWL4AI_API_KEY is the SDKs' name and wins.
var keyEnvVars = []string{"CRAWL4AI_API_KEY", "CRAWL4AI_KEY"}

// a job's status once it no longer changes by itself
var jobStopped = []string{"done", "paused"}

// Client is the Crawl4AI Cloud client. It is safe to use from many goroutines at once.
type Client struct {
	key        string
	baseURL    string
	timeout    time.Duration
	maxRetries int
	http       *http.Client
}

// Option changes one setting of NewClient.
type Option func(*Client)

// WithAPIKey sets the key; without it the key is read from CRAWL4AI_API_KEY.
func WithAPIKey(key string) Option { return func(c *Client) { c.key = key } }

// WithBaseURL sets the API address.
func WithBaseURL(baseURL string) Option { return func(c *Client) { c.baseURL = baseURL } }

// WithTimeout sets how long to wait for an answer, and between two parts of a streamed answer.
func WithTimeout(d time.Duration) Option { return func(c *Client) { c.timeout = d } }

// WithMaxRetries sets how many times a busy or rate-limited call is sent again.
func WithMaxRetries(n int) Option { return func(c *Client) { c.maxRetries = n } }

// WithHTTPClient sends the calls through your own *http.Client (for a proxy, say).
func WithHTTPClient(h *http.Client) Option { return func(c *Client) { c.http = h } }

// defaultHTTP is http.DefaultClient, except that it does not follow a redirect to another origin:
// Go keeps the Authorization header when https turns into http on the same host. The 3xx comes back
// as the error. A client passed to WithHTTPClient keeps its own redirect rules.
var defaultHTTP = &http.Client{CheckRedirect: func(req *http.Request, via []*http.Request) error {
	if req.URL.Scheme != via[0].URL.Scheme || req.URL.Host != via[0].URL.Host {
		return http.ErrUseLastResponse
	}
	if len(via) >= 10 {
		return errors.New("stopped after 10 redirects")
	}
	return nil
}}

// NewClient returns a client. With no key, and a key with a character a header cannot carry, it
// returns an ErrAuthentication error (without the key).
//
//	client, err := crawl4ai.NewClient(crawl4ai.WithTimeout(60 * time.Second))
func NewClient(opts ...Option) (*Client, error) {
	c := &Client{baseURL: BaseURL, timeout: DefaultTimeout, maxRetries: DefaultMaxRetries, http: defaultHTTP}
	for _, opt := range opts {
		opt(c)
	}
	for _, name := range keyEnvVars {
		if c.key == "" {
			c.key = os.Getenv(name)
		}
	}
	c.key = strings.TrimSpace(c.key)
	if c.key == "" {
		return nil, &Error{Kind: ErrAuthentication, Message: "No API key: pass WithAPIKey or set CRAWL4AI_API_KEY."}
	}
	for _, r := range c.key {
		if r < 0x21 || r > 0x7e {
			return nil, &Error{Kind: ErrAuthentication, Message: "The API key has a character that is not allowed."}
		}
	}
	c.baseURL = strings.TrimRight(c.baseURL, "/")
	return c, nil
}

// String keeps the key out of logs: fmt prints the client without it, as a Client or a *Client.
func (c Client) String() string { return "crawl4ai.Client{" + c.baseURL + "}" }

// GoString is String for %#v.
func (c Client) GoString() string { return c.String() }

// call is one request: its path, query and JSON body. once marks a call that must never run twice:
// it is not retried after a 500 or a lost connection.
type call struct {
	method string
	path   string
	query  url.Values
	body   any
	once   bool
}

// idleTimer cancels a request after d with no progress. touch starts the count again, stop ends it.
type idleTimer struct {
	t       *time.Timer
	d       time.Duration
	expired atomic.Bool
}

func newIdleTimer(ctx context.Context, d time.Duration) (*idleTimer, context.Context, context.CancelFunc) {
	ctx, cancel := context.WithCancel(ctx)
	it := &idleTimer{d: d}
	it.t = time.AfterFunc(d, func() {
		it.expired.Store(true)
		cancel()
	})
	return it, ctx, cancel
}

func (it *idleTimer) touch() { it.t.Reset(it.d) }
func (it *idleTimer) stop()  { it.t.Stop() }

// touchReader starts the idle count again each time data arrives.
type touchReader struct {
	r  io.Reader
	it *idleTimer
}

func (t touchReader) Read(p []byte) (int, error) {
	n, err := t.r.Read(p)
	if n > 0 {
		t.it.touch()
	}
	return n, err
}

// sleep waits d or until ctx ends. Tests replace it so retries do not wait.
var sleep = func(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}

// shouldRetry reports whether a request that got `status` is worth sending again.
// 429 and 503 mean the server did not start the work, so every request retries them.
// 500 and 504 retry only when `safe` (sending the request twice cannot run the work twice).
func shouldRetry(status int, safe bool) bool {
	return status == 429 || status == 503 || (safe && (status == 500 || status == 504))
}

// retryDelay is the wait before retry number `attempt` (0 = the first retry): the server's
// Retry-After in seconds when it sends one (at most 60 s), else 0.5 s doubled each time, at most
// 8 s, with random jitter so many clients do not retry at the same moment.
func retryDelay(attempt int, retryAfter string) time.Duration {
	if s, err := strconv.Atoi(retryAfter); err == nil && s >= 0 {
		return min(time.Duration(s)*time.Second, 60*time.Second)
	}
	d := min(500*time.Millisecond<<min(attempt, 4), 8*time.Second)
	return time.Duration(float64(d) * (0.5 + rand.Float64()/2))
}

// errorFrom builds the error for an error answer from its status and body.
//
// The server sends {"error": code, "message": ..., "actions": ...}, /scrape sends
// {"ok": false, "reason": code}, and some errors send plain text or nothing.
func errorFrom(status int, text []byte) *Error {
	var body map[string]any
	_ = json.Unmarshal(text, &body) // plain text or empty: the message falls back to the text
	code := ""
	if v := body["error"]; v != nil {
		code = fmt.Sprint(v)
	} else if v := body["reason"]; v != nil {
		code = fmt.Sprint(v)
	}
	message, _ := body["message"].(string)
	if message == "" {
		message = code
	}
	if message == "" {
		runes := []rune(strings.TrimSpace(string(text)))
		message = string(runes[:min(len(runes), 500)])
	}
	if message == "" {
		message = "HTTP " + strconv.Itoa(status)
	}
	kind := errorKinds[status]
	if kind == nil && status >= 500 {
		kind = ErrServer
	}
	actions, _ := body["actions"].(map[string]any)
	return &Error{Kind: kind, Status: status, Code: code, Message: message, Actions: actions}
}

// failed turns a failure to send or read into an *Error: no answer in time (our timeout or the
// caller's own http.Client's), the caller's own context ending, or a lost connection.
func failed(ctx context.Context, it *idleTimer, path string, err error) *Error {
	var ne net.Error
	switch {
	case it != nil && it.expired.Load():
		return &Error{Kind: ErrTimeout, Message: path + ": no answer in time", Err: err}
	case ctx.Err() != nil:
		return stopped(ctx, path)
	case errors.As(err, &ne) && ne.Timeout():
		return &Error{Kind: ErrTimeout, Message: path + ": no answer in time", Err: err}
	default:
		return &Error{Kind: ErrConnection, Message: path + ": " + err.Error(), Err: err}
	}
}

// stopped is the error when the caller's context ended: a deadline is an ErrTimeout, a cancel has
// no kind. Both wrap the context's error, so errors.Is(err, context.Canceled) works.
func stopped(ctx context.Context, path string) *Error {
	e := &Error{Message: path + ": " + ctx.Err().Error(), Err: ctx.Err()}
	if ctx.Err() == context.DeadlineExceeded {
		e.Kind = ErrTimeout
	}
	return e
}

// decode parses JSON from the server; an answer that is not JSON (a proxy's HTML page, say) is an ErrConnection.
func decode(path string, text []byte, v any) error {
	if err := json.Unmarshal(text, v); err != nil {
		runes := []rune(string(text))
		return &Error{Kind: ErrConnection, Message: path + ": the answer is not JSON: " + string(runes[:min(len(runes), 100)]), Err: err}
	}
	return nil
}

// open sends one request and returns the success answer with its running idle timer and the
// cancel the caller calls once the body is read.
//
//  1. Send. A failure to send is retried only when the call is not `once`; no answer in time is
//     never retried (the server may still be working on it).
//  2. On 429 / 503 (and 500 / 504 when not `once`) wait retryDelay and send again, up to
//     maxRetries times.
//  3. Any other error answer returns the error errorFrom builds.
func (c *Client) open(ctx context.Context, k call) (*http.Response, *idleTimer, context.CancelFunc, error) {
	target := c.baseURL + k.path
	if len(k.query) > 0 {
		target += "?" + k.query.Encode()
	}
	var payload []byte
	if k.body != nil {
		var err error
		if payload, err = json.Marshal(k.body); err != nil {
			return nil, nil, nil, &Error{Kind: ErrBadRequest, Message: k.path + ": " + err.Error(), Err: err}
		}
	}
	for attempt := 0; ; attempt++ {
		last := attempt >= c.maxRetries
		it, rctx, cancel := newIdleTimer(ctx, c.timeout)
		// ---- 1. Send ----
		req, err := http.NewRequestWithContext(rctx, k.method, target, bytes.NewReader(payload))
		if err != nil {
			it.stop()
			cancel()
			return nil, nil, nil, &Error{Message: k.path + ": " + err.Error(), Err: err}
		}
		req.Header.Set("Authorization", "Bearer "+c.key)
		req.Header.Set("User-Agent", "crawl4ai-cloud-go/"+Version)
		if payload != nil {
			req.Header.Set("Content-Type", "application/json")
		}
		resp, err := c.http.Do(req)
		if err != nil {
			it.stop()
			cancel()
			if e := failed(ctx, it, k.path, err); e.Kind != ErrConnection || last || k.once {
				return nil, nil, nil, e
			}
			if err := sleep(ctx, retryDelay(attempt, "")); err != nil {
				return nil, nil, nil, stopped(ctx, k.path)
			}
			continue
		}
		if resp.StatusCode >= 200 && resp.StatusCode < 300 {
			return resp, it, cancel, nil
		}
		// ---- 2. Retry ----
		text, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
		resp.Body.Close()
		it.stop()
		cancel()
		if err != nil && (it.expired.Load() || ctx.Err() != nil) {
			return nil, nil, nil, failed(ctx, it, k.path, err)
		}
		if last || !shouldRetry(resp.StatusCode, !k.once) {
			// ---- 3. Return the error ----
			return nil, nil, nil, errorFrom(resp.StatusCode, text)
		}
		if err := sleep(ctx, retryDelay(attempt, resp.Header.Get("Retry-After"))); err != nil {
			return nil, nil, nil, stopped(ctx, k.path)
		}
	}
}

type answer interface{ meta() *Meta }

// do sends one request and returns its JSON answer, with the cost headers and the raw answer in Meta.
func do[T any, P interface {
	*T
	answer
}](ctx context.Context, c *Client, k call) (*T, error) {
	resp, it, cancel, err := c.open(ctx, k)
	if err != nil {
		return nil, err
	}
	defer cancel()
	defer resp.Body.Close()
	text, err := io.ReadAll(resp.Body)
	it.stop()
	if err != nil {
		return nil, failed(ctx, it, k.path, err)
	}
	out := P(new(T))
	if err := decode(k.path, text, out); err != nil {
		return nil, err
	}
	m := out.meta()
	m.Raw = text
	m.Cost = header(resp, "X-C4-Cost")
	m.Balance = header(resp, "X-C4-Balance")
	m.AllowanceLeft = header(resp, "X-C4-Allowance-Left")
	return (*T)(out), nil
}

// header reads a cost header as a number; nil when the server did not send it.
func header(resp *http.Response, name string) *float64 {
	v, err := strconv.ParseFloat(resp.Header.Get(name), 64)
	if err != nil {
		return nil
	}
	return &v
}

// lines sends one request and yields each line of its NDJSON answer as it arrives. The time the
// caller spends on a line does not count against the timeout.
func (c *Client) lines(ctx context.Context, k call) iter.Seq2[[]byte, error] {
	return func(yield func([]byte, error) bool) {
		resp, it, cancel, err := c.open(ctx, k)
		if err != nil {
			yield(nil, err)
			return
		}
		defer cancel()
		defer resp.Body.Close()
		defer it.stop()
		r := bufio.NewReader(touchReader{resp.Body, it})
		for {
			line, err := r.ReadBytes('\n')
			if err != nil && err != io.EOF {
				yield(nil, failed(ctx, it, k.path, err)) // a part line is dropped: the error says why
				return
			}
			if len(bytes.TrimSpace(line)) > 0 {
				it.stop() // the caller's own time does not count against the server
				if !yield(line, nil) {
					return
				}
				it.touch()
			}
			if err == io.EOF {
				return
			}
		}
	}
}

// jobPath returns /scrape/jobs/<jobID><tail>, with the id escaped for a URL. An empty id, `.` or
// `..` (which a URL reads as a folder step) is an ErrBadRequest.
func jobPath(jobID, tail string) (string, error) {
	if jobID == "" || jobID == "." || jobID == ".." {
		return "", &Error{Kind: ErrBadRequest, Message: fmt.Sprintf("Not a job id: %q", jobID)}
	}
	return "/scrape/jobs/" + url.PathEscape(jobID) + tail, nil
}

// flag is the 0 or 1 the API takes for a yes/no query field.
func flag(v bool) string {
	if v {
		return "1"
	}
	return "0"
}

type scrapeRequest struct {
	URL  string   `json:"url,omitempty"`
	URLs []string `json:"urls,omitempty"`
	*ScrapeOptions
}

var errBypassCache = &Error{Kind: ErrBadRequest, Message: "BypassCache works only with Scrape."}

// Scrape fetches one page and returns it as clean Markdown and/or HTML (POST /scrape).
//
// Most pages take 1 to 2 s; a page that needs a real browser takes up to 90 s. A site that refuses
// every attempt is an ErrBlocked error (Code `blocked` or `login-wall`). opts may be nil.
//
//	page, err := client.Scrape(ctx, "https://example.com", &crawl4ai.ScrapeOptions{Format: "md"})
//	if err != nil {
//		return err
//	}
//	fmt.Println(page.Markdown)
func (c *Client) Scrape(ctx context.Context, url string, opts *ScrapeOptions) (*ScrapeResult, error) {
	return do[ScrapeResult](ctx, c, call{method: "POST", path: "/scrape", body: scrapeRequest{URL: url, ScrapeOptions: opts}})
}

// ScrapeBatch scrapes up to 50 URLs in one call and yields each one as soon as it is ready
// (POST /scrape/batch), in the order they finish. Each item has its own Cost. opts may be nil.
//
//	for item, err := range client.ScrapeBatch(ctx, []string{"https://example.com", "https://example.org"}, nil) {
//		if err != nil {
//			return err
//		}
//		fmt.Println(item.URL, item.OK)
//	}
func (c *Client) ScrapeBatch(ctx context.Context, urls []string, opts *ScrapeOptions) iter.Seq2[ScrapeBatchItem, error] {
	return func(yield func(ScrapeBatchItem, error) bool) {
		if opts != nil && opts.BypassCache {
			yield(ScrapeBatchItem{}, errBypassCache)
			return
		}
		k := call{method: "POST", path: "/scrape/batch", body: scrapeRequest{URLs: urls, ScrapeOptions: opts}}
		for line, err := range c.lines(ctx, k) {
			var v struct {
				ScrapeBatchItem
				Result  json.RawMessage `json:"result"` // decoded below, so Result.Raw keeps it
				Cost    json.Number     `json:"cost"`
				Summary json.RawMessage `json:"summary"`
			}
			if err == nil {
				err = decode(k.path, line, &v)
			}
			if err == nil && v.Result != nil && string(v.Result) != "null" {
				v.ScrapeBatchItem.Result = &ScrapeResult{Meta: Meta{Raw: v.Result}}
				err = decode(k.path, v.Result, v.ScrapeBatchItem.Result)
			}
			if err != nil {
				yield(ScrapeBatchItem{}, err)
				return
			}
			if v.Summary != nil {
				continue // the last line totals the batch; each item has its own cost
			}
			v.ScrapeBatchItem.Cost, _ = v.Cost.Float64()
			if !yield(v.ScrapeBatchItem, nil) {
				return
			}
		}
	}
}

// StartScrapeJob starts a background job for up to 10,000 URLs and returns at once with its JobID
// (POST /scrape/jobs). Then WaitScrapeJob and GetScrapeJobResults.
//
// Every URL is charged the job's flat price; URLs that never got an answer are refunded when the
// job ends. Not retried on a 500, so a job is never started twice. opts may be nil.
//
//	job, err := client.StartScrapeJob(ctx, []string{"https://example.com", "https://example.org"}, nil)
//	if err != nil {
//		return err
//	}
//	fmt.Println(job.JobID)
func (c *Client) StartScrapeJob(ctx context.Context, urls []string, opts *ScrapeOptions) (*ScrapeJob, error) {
	if opts != nil && opts.BypassCache {
		return nil, errBypassCache
	}
	return do[ScrapeJob](ctx, c, call{method: "POST", path: "/scrape/jobs", body: scrapeRequest{URLs: urls, ScrapeOptions: opts}, once: true})
}

// GetScrapeJobOptions are the options of GetScrapeJob. Full adds every URL's detail.
type GetScrapeJobOptions struct {
	Full bool
}

// GetScrapeJob returns a job's Status, Counts and Usage (GET /scrape/jobs/{id}). opts may be nil.
//
//	job, err := client.GetScrapeJob(ctx, jobID, nil)
//	if err != nil {
//		return err
//	}
//	fmt.Println(job.Status, job.Counts.Done)
func (c *Client) GetScrapeJob(ctx context.Context, jobID string, opts *GetScrapeJobOptions) (*ScrapeJob, error) {
	path, err := jobPath(jobID, "")
	if err != nil {
		return nil, err
	}
	var query url.Values
	if opts != nil && opts.Full {
		query = url.Values{"full": {"1"}}
	}
	return do[ScrapeJob](ctx, c, call{method: "GET", path: path, query: query})
}

// WaitOptions are the options of WaitScrapeJob: how often to check (PollInterval, 2 s when zero)
// and how long to wait in all (Timeout, no limit when zero).
type WaitOptions struct {
	PollInterval time.Duration
	Timeout      time.Duration
}

// WaitScrapeJob checks the job every PollInterval and returns it once its status is `done` (or
// `paused`, which needs you to act). After Timeout it returns an ErrTimeout error. opts may be nil.
//
//	job, err := client.WaitScrapeJob(ctx, jobID, &crawl4ai.WaitOptions{Timeout: 10 * time.Minute})
//	if err != nil {
//		return err
//	}
//	fmt.Println(job.Counts)
func (c *Client) WaitScrapeJob(ctx context.Context, jobID string, opts *WaitOptions) (*ScrapeJob, error) {
	var o WaitOptions
	if opts != nil {
		o = *opts
	}
	if o.PollInterval <= 0 {
		o.PollInterval = 2 * time.Second
	}
	wctx := ctx
	if o.Timeout > 0 {
		var cancel context.CancelFunc
		wctx, cancel = context.WithTimeout(ctx, o.Timeout)
		defer cancel()
	}
	status := "not done"
	for {
		job, err := c.GetScrapeJob(wctx, jobID, nil)
		if err == nil {
			if slices.Contains(jobStopped, job.Status) {
				return job, nil
			}
			status = job.Status
			if sleep(wctx, o.PollInterval) != nil {
				err = stopped(wctx, "/scrape/jobs")
			}
		}
		if err != nil {
			if ctx.Err() == nil && wctx.Err() != nil {
				return nil, &Error{Kind: ErrTimeout, Message: fmt.Sprintf("Job %s is still %s after %s", jobID, status, o.Timeout), Err: err}
			}
			return nil, err
		}
	}
}

// GetScrapeJobResults yields a job's results, one item per URL, fetching page after page for you
// (GET /scrape/jobs/{id}/results). Read them after WaitScrapeJob.
//
//	for item, err := range client.GetScrapeJobResults(ctx, jobID) {
//		if err != nil {
//			return err
//		}
//		fmt.Println(item.URL, item.OK)
//	}
func (c *Client) GetScrapeJobResults(ctx context.Context, jobID string) iter.Seq2[ScrapeJobItem, error] {
	return func(yield func(ScrapeJobItem, error) bool) {
		path, err := jobPath(jobID, "/results")
		if err != nil {
			yield(ScrapeJobItem{}, err)
			return
		}
		for after := 0; ; {
			read := 0
			for line, err := range c.lines(ctx, call{method: "GET", path: path, query: url.Values{"after": {strconv.Itoa(after)}}}) {
				var item ScrapeJobItem
				if err == nil {
					err = decode(path, line, &item)
				}
				item.Raw = bytes.TrimSpace(line)
				if err != nil {
					yield(ScrapeJobItem{}, err)
					return
				}
				read++
				if !yield(item, nil) {
					return
				}
			}
			if read == 0 {
				return // an empty page: no more results
			}
			after += read
		}
	}
}

// RetryScrapeJob runs a job's failed URLs again (POST /scrape/jobs/{id}/retry); Retrying says how many.
//
//	retry, err := client.RetryScrapeJob(ctx, jobID)
//	if err != nil {
//		return err
//	}
//	fmt.Println(retry.Retrying)
func (c *Client) RetryScrapeJob(ctx context.Context, jobID string) (*ScrapeJobRetry, error) {
	path, err := jobPath(jobID, "/retry")
	if err != nil {
		return nil, err
	}
	return do[ScrapeJobRetry](ctx, c, call{method: "POST", path: path, once: true})
}

// SearchOptions are the options of Search. Rich adds follow-up questions, related queries, an
// entity card, videos and news.
type SearchOptions struct {
	Rich bool // add follow-up questions, related queries, an entity card, videos and news
	Deep bool // also read the top 10 pages into each result's Markdown: up to 5 s slower, each page with text costs one plain scrape page
}

// Search searches the web and returns ranked, cleaned results (GET /search). q is at most 512
// characters. opts may be nil.
//
//	res, err := client.Search(ctx, "rust web crawler", nil)
//	if err != nil {
//		return err
//	}
//	for _, r := range res.Results {
//		fmt.Println(r.Title, r.URL)
//	}
func (c *Client) Search(ctx context.Context, q string, opts *SearchOptions) (*SearchResult, error) {
	query := url.Values{"q": {q}}
	if opts != nil && opts.Rich {
		query.Set("rich", "1")
	}
	if opts != nil && opts.Deep {
		query.Set("deep", "1")
	}
	return do[SearchResult](ctx, c, call{method: "GET", path: "/search", query: query})
}

// SerpOptions are the options of Serp. An empty field is left out.
type SerpOptions struct {
	Country  string // the Google page's country (`us`)
	Language string // the Google page's language (`en`)
	Location string // a city or region, for example `Austin, TX`
	Num      int    // results per page, 10 to 100 in steps of 10
	Page     int    // which page, in steps of Num
	Time     string // only results from the past `hour`, `day`, `week`, `month` or `year`
	Fresh    bool   // skip the cache, at the live price
	Source   string // `google` for the road that also returns the AI Overview
}

// Serp returns Google's results page as data: true ranks and every block Google showed
// (GET /serp, beta). opts may be nil.
//
//	res, err := client.Serp(ctx, "best crm software", &crawl4ai.SerpOptions{Country: "us"})
//	if err != nil {
//		return err
//	}
//	for _, r := range res.Results {
//		fmt.Println(r.Position, r.Domain)
//	}
func (c *Client) Serp(ctx context.Context, q string, opts *SerpOptions) (*SerpResult, error) {
	query := url.Values{"q": {q}}
	if opts != nil {
		for name, value := range map[string]string{"country": opts.Country, "language": opts.Language, "location": opts.Location, "time": opts.Time, "source": opts.Source} {
			if value != "" {
				query.Set(name, value)
			}
		}
		if opts.Num != 0 {
			query.Set("num", strconv.Itoa(opts.Num))
		}
		if opts.Page != 0 {
			query.Set("page", strconv.Itoa(opts.Page))
		}
		if opts.Fresh {
			query.Set("fresh", "1")
		}
	}
	return do[SerpResult](ctx, c, call{method: "GET", path: "/serp", query: query})
}

// AnswerOptions are the options of Answer.
//
// Schema is a JSON Schema (any value that marshals to one); Answer.Text is then JSON of that
// shape. Deep set to crawl4ai.Bool(false) returns only an answer that is readily available,
// without reading pages.
type AnswerOptions struct {
	Schema any
	Deep   *bool
}

// Bool returns a pointer to v, for an option where unset and false differ.
func Bool(v bool) *bool { return &v }

// Answer answers a question from the web, with its sources (GET /answer, experimental). When there
// is no answer, Answered is false and the call costs nothing. opts may be nil.
//
//	res, err := client.Answer(ctx, "why is the sky blue", nil)
//	if err != nil {
//		return err
//	}
//	if res.Answered {
//		fmt.Println(res.Answer.Text)
//	}
func (c *Client) Answer(ctx context.Context, q string, opts *AnswerOptions) (*AnswerResult, error) {
	query := url.Values{"q": {q}}
	if opts != nil {
		if opts.Schema != nil {
			schema, err := json.Marshal(opts.Schema)
			if err != nil {
				return nil, &Error{Kind: ErrBadRequest, Message: "Schema: " + err.Error(), Err: err}
			}
			query.Set("schema", string(schema))
		}
		if opts.Deep != nil {
			query.Set("deep", flag(*opts.Deep))
		}
	}
	return do[AnswerResult](ctx, c, call{method: "GET", path: "/answer", query: query})
}

// ExtractOptions are the options of Extract: a URL (the page is fetched for you) or Content (your
// own text, Markdown or HTML), plus Instruction (what to pull out, in plain English) and/or Schema
// (a JSON Schema each record must match). Example is a sample of the shape you want.
type ExtractOptions struct {
	URL         string `json:"url,omitempty"`
	Content     string `json:"content,omitempty"`
	Instruction string `json:"instruction,omitempty"`
	Schema      any    `json:"schema,omitempty"`
	Example     any    `json:"example,omitempty"`
}

// Extract pulls structured data out of a page with a language model (POST /extract).
//
//	res, err := client.Extract(ctx, &crawl4ai.ExtractOptions{URL: "https://news.ycombinator.com", Instruction: "the top 3 story titles"})
//	if err != nil {
//		return err
//	}
//	fmt.Println(string(res.Data))
func (c *Client) Extract(ctx context.Context, opts *ExtractOptions) (*ExtractResult, error) {
	if opts == nil {
		opts = &ExtractOptions{}
	}
	return do[ExtractResult](ctx, c, call{method: "POST", path: "/extract", body: opts})
}
