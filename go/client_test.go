// Unit tests against a fake server (httptest): no key, no network, no cost.

package crawl4ai

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

var page = map[string]any{"ok": true, "markdown": "# Hi", "engine": "archive", "ms": 4, "text_len": 2, "new_field": 1}

type sent struct {
	method string
	path   string // escaped, as it went on the wire
	query  string
	header http.Header
	body   map[string]any
}

type server struct {
	client *Client
	url    string
	mu     sync.Mutex
	sent   []sent
	waits  []time.Duration
}

func (s *server) got() []sent {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]sent(nil), s.sent...)
}

// fake starts a server that gets `answers` in order, one per request (the last one repeats), and
// records what it got. Retries and polling do not wait; the waits are recorded instead.
func fake(t *testing.T, answers ...http.HandlerFunc) *server {
	t.Helper()
	s := &server{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		var body map[string]any
		_ = json.Unmarshal(raw, &body)
		s.mu.Lock()
		s.sent = append(s.sent, sent{r.Method, r.URL.EscapedPath(), r.URL.RawQuery, r.Header.Clone(), body})
		n := len(s.sent)
		s.mu.Unlock()
		answers[min(n, len(answers))-1](w, r)
	}))
	t.Cleanup(srv.Close)
	s.url = srv.URL
	real := sleep
	sleep = func(ctx context.Context, d time.Duration) error {
		s.mu.Lock()
		s.waits = append(s.waits, d)
		s.mu.Unlock()
		return ctx.Err()
	}
	t.Cleanup(func() { sleep = real })
	s.client = s.newClient(t)
	return s
}

func (s *server) newClient(t *testing.T, opts ...Option) *Client {
	t.Helper()
	c, err := NewClient(append([]Option{WithAPIKey("sk_test"), WithBaseURL(s.url)}, opts...)...)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func answerJSON(status int, body any, headers ...string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		for i := 0; i+1 < len(headers); i += 2 {
			w.Header().Set(headers[i], headers[i+1])
		}
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(body)
	}
}

func answerText(status int, text string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(status)
		_, _ = io.WriteString(w, text)
	}
}

func answerLines(lines ...any) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		for _, line := range lines {
			_ = json.NewEncoder(w).Encode(line)
		}
	}
}

// hangUp closes the connection without an answer.
func hangUp(w http.ResponseWriter, r *http.Request) {
	conn, _, _ := w.(http.Hijacker).Hijack()
	conn.Close()
}

func isKind(t *testing.T, err error, kind error) *Error {
	t.Helper()
	var e *Error
	if !errors.As(err, &e) || !errors.Is(err, kind) {
		t.Fatalf("want a %v *Error, got %#v", kind, err)
	}
	return e
}

var ctx = context.Background()

func TestKeyFromEnvAndMissing(t *testing.T) {
	t.Setenv("CRAWL4AI_API_KEY", "")
	t.Setenv("CRAWL4AI_KEY", "")
	s := fake(t, answerJSON(200, page))
	c, err := NewClient(WithBaseURL(s.url))
	if err != nil {
		t.Fatal(err)
	}
	_, err = c.Scrape(ctx, "https://example.com", nil)
	isKind(t, err, ErrAuthentication)
	if len(s.got()) != 0 {
		t.Fatal("a call without a key was sent")
	}

	t.Setenv("CRAWL4AI_KEY", "sk_old_name")
	c, _ = NewClient(WithBaseURL(s.url))
	_, _ = c.Scrape(ctx, "https://example.com", nil)
	t.Setenv("CRAWL4AI_API_KEY", "sk_new_name")
	c, _ = NewClient(WithBaseURL(s.url))
	_, _ = c.Scrape(ctx, "https://example.com", nil)
	got := s.got()
	if got[0].header.Get("Authorization") != "Bearer sk_old_name" || got[1].header.Get("Authorization") != "Bearer sk_new_name" {
		t.Fatalf("keys sent: %q, %q", got[0].header.Get("Authorization"), got[1].header.Get("Authorization"))
	}
}

func TestKeyWithABadCharacterFailsWithoutTheKey(t *testing.T) {
	for _, key := range []string{"sk_live_SEC\nRET", "sk_live_SECRÉT", "sk live"} {
		_, err := NewClient(WithAPIKey(key))
		isKind(t, err, ErrAuthentication)
		if strings.Contains(err.Error(), "SEC") {
			t.Fatalf("the error shows the key: %v", err)
		}
	}
	s := fake(t, answerJSON(200, page))
	_, _ = s.newClient(t, WithAPIKey("sk_test\n")).Scrape(ctx, "https://example.com", nil)
	if got := s.got()[0].header.Get("Authorization"); got != "Bearer sk_test" {
		t.Fatalf("sent %q", got)
	}
}

func TestTheKeyIsNotPrinted(t *testing.T) {
	c, _ := NewClient(WithAPIKey("sk_live_SECRET"))
	for _, format := range []string{"%v", "%+v", "%#v", "%s"} {
		for _, value := range []any{c, *c} {
			if text := fmt.Sprintf(format, value); strings.Contains(text, "SECRET") {
				t.Fatalf("%s prints the key: %s", format, text)
			}
		}
	}
}

func TestScrapeSendsOnlySetFieldsAndReadsResult(t *testing.T) {
	s := fake(t, answerJSON(200, page, "X-C4-Cost", "0.500", "X-C4-Balance", "99.5"))
	p, err := s.client.Scrape(ctx, "https://example.com", &ScrapeOptions{Format: "md", Parse: &Parse{Links: true}})
	if err != nil {
		t.Fatal(err)
	}
	got := s.got()[0]
	if got.method != "POST" || got.path != "/scrape" || got.header.Get("Content-Type") != "application/json" {
		t.Fatalf("sent %s %s", got.method, got.path)
	}
	if want := `map[format:md parse:map[links:true] url:https://example.com]`; fmt.Sprint(got.body) != want {
		t.Fatalf("body %v", got.body)
	}
	if !p.OK || p.Markdown != "# Hi" || p.Engine != "archive" || p.TextLen != 2 || p.HTML != "" {
		t.Fatalf("result %+v", p)
	}
	if *p.Cost != 0.5 || *p.Balance != 99.5 || p.AllowanceLeft != nil {
		t.Fatalf("costs %v %v %v", p.Cost, p.Balance, p.AllowanceLeft)
	}
	if !strings.Contains(string(p.Raw), `"new_field":1`) { // a field the SDK does not know is kept
		t.Fatalf("raw %s", p.Raw)
	}
}

func TestParseAllAndBypassCacheAreSent(t *testing.T) {
	s := fake(t, answerJSON(200, page))
	_, _ = s.client.Scrape(ctx, "https://example.com", &ScrapeOptions{Parse: &Parse{All: true}, BypassCache: true})
	if want := `map[bypass_cache:true parse:true url:https://example.com]`; fmt.Sprint(s.got()[0].body) != want {
		t.Fatalf("body %v", s.got()[0].body)
	}
}

func TestBypassCacheIsRefusedOutsideScrape(t *testing.T) {
	s := fake(t, answerJSON(200, page))
	_, err := s.client.StartScrapeJob(ctx, []string{"https://a.com"}, &ScrapeOptions{BypassCache: true})
	isKind(t, err, ErrBadRequest)
	for _, err := range s.client.ScrapeBatch(ctx, []string{"https://a.com"}, &ScrapeOptions{BypassCache: true}) {
		isKind(t, err, ErrBadRequest)
	}
	if len(s.got()) != 0 {
		t.Fatal("a request was sent")
	}
}

func TestErrorAnswersBecomeErrors(t *testing.T) {
	cases := []struct {
		name   string
		answer http.HandlerFunc
		kind   error
		code   string
	}{
		{"402", answerJSON(402, map[string]any{"error": "no_credit", "message": "Out of credits", "actions": map[string]any{"subscribe": "u"}}), ErrPaymentRequired, "no_credit"},
		{"403 login-wall", answerJSON(403, map[string]any{"ok": false, "reason": "login-wall"}), ErrBlocked, "login-wall"},
		{"401 with an empty body", answerText(401, ""), ErrAuthentication, ""},
		{"422 with plain text", answerText(422, "missing field `url`"), ErrBadRequest, ""},
		{"404", answerJSON(404, map[string]any{"error": "not_available"}), ErrNotFound, "not_available"},
		{"502", answerJSON(502, map[string]any{"ok": false, "reason": "no-answer"}), ErrServer, "no-answer"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := fake(t, tc.answer).client.Scrape(ctx, "https://example.com", nil)
			e := isKind(t, err, tc.kind)
			if e.Code != tc.code || e.Message == "" {
				t.Fatalf("code %q message %q", e.Code, e.Message)
			}
		})
	}
	_, err := fake(t, cases[0].answer).client.Scrape(ctx, "https://example.com", nil)
	e := isKind(t, err, ErrPaymentRequired)
	if e.Message != "Out of credits" || e.Actions["subscribe"] != "u" || e.Status != 402 {
		t.Fatalf("%+v", e)
	}
	if _, err := fake(t, answerText(422, "missing field `url`")).client.Scrape(ctx, "x", nil); !strings.Contains(err.Error(), "missing field") {
		t.Fatalf("message %v", err)
	}
}

func TestBusyIsRetriedWaitingRetryAfter(t *testing.T) {
	s := fake(t, answerJSON(503, map[string]any{"error": "busy"}, "Retry-After", "7"), answerJSON(200, map[string]any{"results": []any{}}))
	if _, err := s.client.Search(ctx, "x", nil); err != nil {
		t.Fatal(err)
	}
	if len(s.got()) != 2 || len(s.waits) != 1 || s.waits[0] != 7*time.Second {
		t.Fatalf("sent %d, waits %v", len(s.got()), s.waits)
	}
}

func TestRetriesStopAfterMaxRetries(t *testing.T) {
	s := fake(t, answerJSON(429, map[string]any{"error": "rate_limited"}))
	_, err := s.newClient(t, WithMaxRetries(2)).Search(ctx, "x", nil)
	isKind(t, err, ErrRateLimit)
	if len(s.got()) != 3 {
		t.Fatalf("sent %d", len(s.got()))
	}
}

func TestA500IsRetriedForSearchButNotForStartingAJob(t *testing.T) {
	s := fake(t, answerText(500, "oops"), answerJSON(200, map[string]any{"results": []any{}}))
	if _, err := s.client.Search(ctx, "x", nil); err != nil || len(s.got()) != 2 {
		t.Fatalf("search: %v, sent %d", err, len(s.got()))
	}
	s = fake(t, answerText(500, "oops"))
	_, err := s.client.StartScrapeJob(ctx, []string{"https://a.com"}, nil)
	isKind(t, err, ErrServer)
	if len(s.got()) != 1 {
		t.Fatalf("a job was started %d times", len(s.got()))
	}
	s = fake(t, answerText(500, "oops"))
	_, err = s.client.RetryScrapeJob(ctx, "j")
	isKind(t, err, ErrServer)
	if len(s.got()) != 1 {
		t.Fatalf("retry was sent %d times", len(s.got()))
	}
}

func TestANetworkFailureIsRetriedForSearchButNotForStartingAJob(t *testing.T) {
	s := fake(t, hangUp, answerJSON(200, map[string]any{"results": []any{}}))
	if _, err := s.client.Search(ctx, "x", nil); err != nil || len(s.got()) != 2 {
		t.Fatalf("search: %v, sent %d", err, len(s.got()))
	}
	s = fake(t, hangUp)
	_, err := s.client.StartScrapeJob(ctx, []string{"https://a.com"}, nil)
	isKind(t, err, ErrConnection)
	if len(s.got()) != 1 {
		t.Fatalf("a job was started %d times", len(s.got()))
	}
}

func TestNoAnswerInTimeIsATimeoutAndIsNotRetried(t *testing.T) {
	s := fake(t, func(w http.ResponseWriter, r *http.Request) { <-r.Context().Done() })
	_, err := s.newClient(t, WithTimeout(20*time.Millisecond)).Search(ctx, "x", nil)
	isKind(t, err, ErrTimeout)
	isKind(t, err, ErrConnection)
	if len(s.got()) != 1 {
		t.Fatalf("sent %d", len(s.got()))
	}
}

func TestYourOwnHTTPClientsTimeoutIsATimeoutAndIsNotRetried(t *testing.T) {
	s := fake(t, func(w http.ResponseWriter, r *http.Request) { <-r.Context().Done() })
	c := s.newClient(t, WithHTTPClient(&http.Client{Timeout: 20 * time.Millisecond}), WithMaxRetries(1))
	_, err := c.Search(ctx, "x", nil)
	isKind(t, err, ErrTimeout)
	if len(s.got()) != 1 {
		t.Fatalf("sent %d", len(s.got()))
	}
}

func TestTheCallersCancelStopsTheCall(t *testing.T) {
	s := fake(t, answerJSON(503, map[string]any{"error": "busy"}))
	done, cancel := context.WithCancel(ctx)
	cancel()
	_, err := s.client.Search(done, "x", nil)
	if !errors.Is(err, context.Canceled) || len(s.got()) > 1 {
		t.Fatalf("err %v, sent %d", err, len(s.got()))
	}
}

func TestAnAnswerThatIsNotJSONIsAConnectionError(t *testing.T) {
	html := answerText(200, "<html>proxy login</html>")
	_, err := fake(t, html).client.Search(ctx, "x", nil)
	isKind(t, err, ErrConnection)
	for _, err := range fake(t, html).client.ScrapeBatch(ctx, []string{"https://a.com"}, nil) {
		isKind(t, err, ErrConnection)
	}
}

func TestScrapeBatchYieldsItemsAndSkipsTheSummary(t *testing.T) {
	s := fake(t, answerLines(
		map[string]any{"url": "https://a.com", "ok": true, "result": page, "cost": "0.500"},
		map[string]any{"url": "https://b.com", "ok": false, "error": "blocked", "cost": "0"},
		map[string]any{"summary": map[string]any{"cost": "0.500", "urls": 2}},
	))
	var items []ScrapeBatchItem
	for item, err := range s.client.ScrapeBatch(ctx, []string{"https://a.com", "https://b.com"}, &ScrapeOptions{Format: "md"}) {
		if err != nil {
			t.Fatal(err)
		}
		items = append(items, item)
	}
	if len(items) != 2 || items[0].Result.Markdown != "# Hi" || items[0].Cost != 0.5 || items[1].Error != "blocked" {
		t.Fatalf("%+v", items)
	}
	if want := `map[format:md urls:[https://a.com https://b.com]]`; fmt.Sprint(s.got()[0].body) != want {
		t.Fatalf("body %v", s.got()[0].body)
	}
}

func TestBatchAndJobItemsKeepTheRawAnswer(t *testing.T) {
	s := fake(t, answerLines(map[string]any{"url": "https://a.com", "ok": true, "result": page}))
	for item, err := range s.client.ScrapeBatch(ctx, []string{"https://a.com"}, nil) {
		if err != nil || !strings.Contains(string(item.Result.Raw), `"new_field":1`) {
			t.Fatalf("%s %v", item.Result.Raw, err)
		}
	}
	s = fake(t, answerLines(map[string]any{"url": "https://a.com", "ok": true, "new_field": 1}), answerText(200, ""))
	for item, err := range s.client.GetScrapeJobResults(ctx, "j") {
		if err != nil || !strings.Contains(string(item.Raw), `"new_field":1`) {
			t.Fatalf("%s %v", item.Raw, err)
		}
	}
}

func TestALineSplitAcrossTwoChunksIsReadWhole(t *testing.T) {
	s := fake(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, `{"url": "https://a.c`)
		w.(http.Flusher).Flush()
		time.Sleep(10 * time.Millisecond)
		_, _ = io.WriteString(w, `om", "ok": true}`+"\n")
	})
	for item, err := range s.client.ScrapeBatch(ctx, []string{"https://a.com"}, nil) {
		if err != nil || item.URL != "https://a.com" {
			t.Fatalf("%+v %v", item, err)
		}
	}
}

func TestAStreamThatStopsSendingIsATimeout(t *testing.T) {
	s := fake(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, `{"url": "https://a.com", "ok": true}`+"\n")
		w.(http.Flusher).Flush()
		<-r.Context().Done()
	})
	var urls []string
	var last error
	for item, err := range s.newClient(t, WithTimeout(20*time.Millisecond)).ScrapeBatch(ctx, []string{"https://a.com", "https://b.com"}, nil) {
		if err != nil {
			last = err
			break
		}
		urls = append(urls, item.URL)
	}
	isKind(t, last, ErrTimeout)
	if fmt.Sprint(urls) != "[https://a.com]" {
		t.Fatalf("urls %v", urls)
	}
}

func TestAStreamThatStopsMidLineIsATimeout(t *testing.T) {
	s := fake(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, `{"url":"https://exa`)
		w.(http.Flusher).Flush()
		<-r.Context().Done()
	})
	for _, err := range s.newClient(t, WithTimeout(50*time.Millisecond)).ScrapeBatch(ctx, []string{"https://a.com"}, nil) {
		isKind(t, err, ErrTimeout)
	}
}

func TestTimeTheCallerSpendsBetweenLinesIsNotATimeout(t *testing.T) {
	s := fake(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, `{"url": "https://a.com", "ok": true}`+"\n")
		w.(http.Flusher).Flush()
		time.Sleep(10 * time.Millisecond) // the second line comes while the caller holds the first
		_, _ = io.WriteString(w, `{"url": "https://b.com", "ok": true}`+"\n")
	})
	var urls []string
	for item, err := range s.newClient(t, WithTimeout(20*time.Millisecond)).ScrapeBatch(ctx, []string{"https://a.com", "https://b.com"}, nil) {
		if err != nil {
			t.Fatal(err)
		}
		urls = append(urls, item.URL)
		time.Sleep(40 * time.Millisecond) // twice the timeout
	}
	if fmt.Sprint(urls) != "[https://a.com https://b.com]" {
		t.Fatalf("urls %v", urls)
	}
}

func TestWaitAndResultsReadEveryPage(t *testing.T) {
	s := fake(t,
		answerJSON(200, map[string]any{"job_id": "j", "status": "running"}),
		answerJSON(200, map[string]any{"job_id": "j", "status": "done", "counts": map[string]any{"done": 3}}),
		answerLines(map[string]any{"url": "https://a.com", "ok": true}, map[string]any{"url": "https://b.com", "ok": true}),
		answerLines(map[string]any{"url": "https://c.com", "ok": false, "content_hash": nil, "error": map[string]any{"class": "blocked"}}),
		answerText(200, ""),
	)
	job, err := s.client.WaitScrapeJob(ctx, "j", &WaitOptions{PollInterval: time.Second})
	if err != nil || job.Status != "done" || job.Counts.Done != 3 || fmt.Sprint(s.waits) != "[1s]" {
		t.Fatalf("%+v %v waits %v", job, err, s.waits)
	}
	var urls []string
	for item, err := range s.client.GetScrapeJobResults(ctx, "j") {
		if err != nil {
			t.Fatal(err)
		}
		urls = append(urls, item.URL)
		if item.URL == "https://c.com" && item.Error.Class != "blocked" {
			t.Fatalf("%+v", item)
		}
	}
	got := s.got()
	if fmt.Sprint(urls) != "[https://a.com https://b.com https://c.com]" || got[2].query != "after=0" || got[3].query != "after=2" || got[4].query != "after=3" {
		t.Fatalf("urls %v", urls)
	}
}

func TestWaitTimesOutWithoutSleepingPastItsTimeout(t *testing.T) {
	s := fake(t, answerJSON(200, map[string]any{"job_id": "j", "status": "running"}))
	real := sleep
	sleep = func(ctx context.Context, d time.Duration) error {
		<-ctx.Done() // the poll interval below is an hour: only the timeout ends this wait
		return ctx.Err()
	}
	defer func() { sleep = real }()
	start := time.Now()
	_, err := s.client.WaitScrapeJob(ctx, "j", &WaitOptions{PollInterval: time.Hour, Timeout: 30 * time.Millisecond})
	e := isKind(t, err, ErrTimeout)
	if !strings.Contains(e.Message, "still running") || time.Since(start) > time.Second {
		t.Fatalf("%v after %s", err, time.Since(start))
	}
}

func TestRetryReadsUsage(t *testing.T) {
	s := fake(t, answerJSON(200, map[string]any{"job_id": "j", "retrying": 2, "usage": map[string]any{"units": 2}}))
	r, err := s.client.RetryScrapeJob(ctx, "j")
	if err != nil || r.Retrying != 2 || r.Usage["units"] != float64(2) || s.got()[0].path != "/scrape/jobs/j/retry" {
		t.Fatalf("%+v %v", r, err)
	}
}

func TestSearchSendsDeepAs1AndReadsMarkdownAndDeepPages(t *testing.T) {
	s := fake(t, answerJSON(200, map[string]any{
		"results": []any{map[string]any{"url": "https://a.com", "markdown": "# A"}, map[string]any{"url": "https://b.com"}},
		"deep":    map[string]any{"launched": 2, "got": 1, "from_archive": 0, "late": 1, "ms": 900},
		"usage":   map[string]any{"deep_pages": 1},
	}))
	r, err := s.client.Search(ctx, "x", &SearchOptions{Deep: true})
	if err != nil || r.Results[0].Markdown != "# A" || r.Results[1].Markdown != "" || r.Deep.Got != 1 || r.Usage.DeepPages != 1 {
		t.Fatalf("%+v %v", r, err)
	}
	if want := "deep=1&q=x"; s.got()[0].query != want {
		t.Fatalf("query %s", s.got()[0].query)
	}
}

func TestAnswerSendsTheSchemaAsJSONTextAndDeepAs0(t *testing.T) {
	s := fake(t, answerJSON(200, map[string]any{"answered": true, "answer": map[string]any{"text": `{"name":"Guido"}`}}))
	schema := map[string]any{"type": "object"}
	r, err := s.client.Answer(ctx, "who", &AnswerOptions{Schema: schema, Deep: Bool(false)})
	if err != nil || !r.Answered || r.Answer.Text != `{"name":"Guido"}` {
		t.Fatalf("%+v %v", r, err)
	}
	if want := "deep=0&q=who&schema=%7B%22type%22%3A%22object%22%7D"; s.got()[0].query != want {
		t.Fatalf("query %s", s.got()[0].query)
	}
}

func TestSerpReadsNestedResultsAndKeepsEveryBlock(t *testing.T) {
	s := fake(t, answerJSON(200, map[string]any{
		"results":         []any{map[string]any{"position": 1, "url": "https://a.com", "domain": "a.com"}},
		"blocks":          []any{"organic", "knowledge_panel"},
		"knowledge_panel": map[string]any{"title": "A"},
	}))
	r, err := s.client.Serp(ctx, "crm", &SerpOptions{Country: "us", Num: 20, Fresh: true})
	if err != nil || r.Results[0].Domain != "a.com" || string(r.Block("knowledge_panel")) != `{"title":"A"}` || r.Block("local_pack") != nil {
		t.Fatalf("%+v %v", r, err)
	}
	if want := "country=us&fresh=1&num=20&q=crm"; s.got()[0].query != want {
		t.Fatalf("query %s", s.got()[0].query)
	}
}

func TestExtractTakesAURLOrYourOwnContent(t *testing.T) {
	s := fake(t, answerJSON(200, map[string]any{"ok": true, "data": []any{map[string]any{"price": 5}}}))
	r, err := s.client.Extract(ctx, &ExtractOptions{Content: "<p>Price: $5</p>", Instruction: "the price"})
	if err != nil || string(r.Data) != `[{"price":5}]` {
		t.Fatalf("%+v %v", r, err)
	}
	if want := `map[content:<p>Price: $5</p> instruction:the price]`; fmt.Sprint(s.got()[0].body) != want {
		t.Fatalf("body %v", s.got()[0].body)
	}
}

func TestAValueThatIsNotJSONIsABadRequest(t *testing.T) {
	s := fake(t, answerJSON(200, map[string]any{"ok": true}))
	_, err := s.client.Extract(ctx, &ExtractOptions{Content: "x", Schema: map[string]any{"bad": func() {}}})
	isKind(t, err, ErrBadRequest)
	if len(s.got()) != 0 {
		t.Fatal("a request was sent")
	}
}

func TestTheJobIDIsEscapedInThePath(t *testing.T) {
	s := fake(t, answerJSON(200, map[string]any{"job_id": "a/b?c", "status": "done"}))
	_, _ = s.client.GetScrapeJob(ctx, "a/b?c", &GetScrapeJobOptions{Full: true})
	if got := s.got()[0]; got.path != "/scrape/jobs/a%2Fb%3Fc" || got.query != "full=1" {
		t.Fatalf("path %s query %s", got.path, got.query)
	}
}

func TestAJobIDThatIsAFolderStepIsRefused(t *testing.T) {
	s := fake(t, answerJSON(200, map[string]any{}))
	for _, id := range []string{"", ".", ".."} {
		_, err := s.client.GetScrapeJob(ctx, id, nil)
		isKind(t, err, ErrBadRequest)
		_, err = s.client.RetryScrapeJob(ctx, id)
		isKind(t, err, ErrBadRequest)
		for _, err := range s.client.GetScrapeJobResults(ctx, id) {
			isKind(t, err, ErrBadRequest)
		}
	}
	if len(s.got()) != 0 {
		t.Fatal("a request was sent")
	}
}

func TestRetryDelay(t *testing.T) {
	if d := retryDelay(0, "120"); d != 60*time.Second {
		t.Fatalf("Retry-After is capped at 60 s: %s", d)
	}
	for attempt := range 100 {
		if d := retryDelay(attempt, ""); d <= 0 || d > 8*time.Second {
			t.Fatalf("attempt %d: %s", attempt, d)
		}
	}
}

func TestARedirectToAnotherOriginIsNotFollowed(t *testing.T) {
	other := fake(t, answerJSON(200, map[string]any{"results": []any{}}))
	s := fake(t, func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, other.url+"/search", http.StatusFound)
	})
	_, err := s.client.Search(ctx, "x", nil)
	var e *Error
	if !errors.As(err, &e) || e.Status != http.StatusFound {
		t.Fatalf("err %v", err)
	}
	if len(other.got()) != 0 {
		t.Fatal("the key went to another origin")
	}
}
