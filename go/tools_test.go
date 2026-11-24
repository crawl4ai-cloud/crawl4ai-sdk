package crawl4ai

import (
	"encoding/json"
	"reflect"
	"testing"
)

func TestToolsFindSendsTheFiltersAndReadsThePage(t *testing.T) {
	s := fake(t, answerJSON(200, map[string]any{"tools": []any{map[string]any{"id": "amazon-product", "name": []any{"Amazon", "product"}, "cost": "1 cr", "inputs": []any{"product*"}}}, "total": 3, "next_cursor": "2"}))
	list, err := s.client.Tools.Find(ctx, "amazon product", &FindToolsOptions{Kind: "sites", Essential: true, Limit: 2})
	if err != nil {
		t.Fatal(err)
	}
	got := s.got()[0]
	if got.path != "/tools" || got.query != "essential=true&kind=sites&limit=2&q=amazon+product" {
		t.Fatalf("sent %s?%s", got.path, got.query)
	}
	if list.Tools[0].ID != "amazon-product" || list.Tools[0].Cost != "1 cr" || list.Tools[0].Inputs[0] != "product*" || list.Total != 3 || list.NextCursor != "2" {
		t.Fatalf("read %+v", list)
	}
}

func TestToolsGetAndEstimateReadTheTool(t *testing.T) {
	tool := map[string]any{"id": "scrape", "name": map[string]any{"lead": "Scrape", "rest": "a page"}, "cost": map[string]any{"text": "0.1 cr"}, "inputs": []any{map[string]any{"name": "url", "required": true}}}
	s := fake(t, answerJSON(200, tool, "X-C4-Cost", "0"), answerJSON(200, map[string]any{"tool": "amazon-product", "data": map[string]any{"text": "1 cr"}}))
	got, err := s.client.Tools.Get(ctx, "scrape")
	if err != nil {
		t.Fatal(err)
	}
	if got.Cost.Text != "0.1 cr" || got.Name.Lead != "Scrape" || got.Inputs[0].Name != "url" || !got.Inputs[0].Required {
		t.Fatalf("read %+v", got)
	}
	est, err := s.client.Tools.Estimate(ctx, "amazon-product", map[string]any{"product": "B0"})
	if err != nil || est.Data["text"] != "1 cr" {
		t.Fatalf("estimate %+v, %v", est, err)
	}
	if sent := s.got(); sent[1].method != "POST" || sent[1].path != "/tools/amazon-product/estimate" || sent[1].body["product"] != "B0" {
		t.Fatalf("sent %+v", sent[1])
	}
}

func TestToolsRunPostsTheInputsAndFreshAndReadsRows(t *testing.T) {
	s := fake(t, answerJSON(200, map[string]any{"tool": "amazon-product", "request_id": "req_1", "rows": []any{map[string]any{"asin": "B0"}}, "data": map[string]any{"n": 1}}, "X-C4-Cost", "1.000"))
	run, err := s.client.Tools.Run(ctx, "amazon-product", map[string]any{"product": "B0", "fresh": "an input"}, &RunToolOptions{Fresh: true})
	if err != nil {
		t.Fatal(err)
	}
	got := s.got()[0]
	if !reflect.DeepEqual(got.body, map[string]any{"product": "B0", "fresh": "an input"}) || got.header.Get("Crawl4AI-Fresh") != "true" {
		t.Fatalf("sent %+v", got)
	}
	if run.Rows[0]["asin"] != "B0" || run.RequestID != "req_1" || string(run.Data) != `{"n":1}` || *run.Meta.Cost != 1 {
		t.Fatalf("read %+v", run)
	}
}

func TestToolsErrorsKeepDetailsAndDidYouMean(t *testing.T) {
	s := fake(t,
		answerJSON(422, map[string]any{"error": "invalid_input", "details": []any{map[string]any{"problem": "url is required"}}}),
		answerJSON(404, map[string]any{"error": "tool_not_found", "did_you_mean": []any{"amazon-product"}}),
	)
	_, err := s.client.Tools.Run(ctx, "scrape", map[string]any{}, nil)
	if e := isKind(t, err, ErrBadRequest); e.Message != "invalid_input: url is required" {
		t.Fatalf("message %q", e.Message)
	}
	_, err = s.client.Tools.Get(ctx, "amazon-produc")
	if e := isKind(t, err, ErrNotFound); !reflect.DeepEqual(e.Body["did_you_mean"], []any{"amazon-product"}) {
		t.Fatalf("body %v", e.Body)
	}
}

func TestToolsRunAndBatchAreNotSentAgainAfterA500AndToolFailingIsNotRetried(t *testing.T) {
	s := fake(t, answerJSON(500, map[string]any{"error": "internal"}))
	_, err := s.client.Tools.Run(ctx, "scrape", map[string]any{"url": "https://example.com"}, nil)
	isKind(t, err, ErrServer)
	_, err = s.client.Tools.Batch(ctx, "scrape", []map[string]any{{"url": "https://example.com"}})
	isKind(t, err, ErrServer)
	if n := len(s.got()); n != 2 {
		t.Fatalf("sent %d times, want 2", n)
	}
	s = fake(t, answerJSON(503, map[string]any{"error": "tool_failing"}))
	_, err = s.client.Tools.Get(ctx, "scrape")
	if e := isKind(t, err, ErrServer); e.Code != "tool_failing" || len(s.got()) != 1 {
		t.Fatalf("code %q, sent %d", e.Code, len(s.got()))
	}
}

func TestToolsBatchPostsTheToolAndInputsAndReturnsTheJob(t *testing.T) {
	s := fake(t, answerJSON(202, map[string]any{"tool": "scrape", "data": map[string]any{"job_id": "j_1", "status": "pending"}}))
	run, err := s.client.Tools.Batch(ctx, "scrape", []map[string]any{{"url": "https://example.com"}})
	if err != nil {
		t.Fatal(err)
	}
	got := s.got()[0]
	want := map[string]any{"tool": "scrape", "inputs": []any{map[string]any{"url": "https://example.com"}}}
	if got.path != "/tools/batch" || !reflect.DeepEqual(got.body, want) {
		t.Fatalf("sent %s %v", got.path, got.body)
	}
	var job ScrapeJob
	if err := json.Unmarshal(run.Data, &job); err != nil || job.JobID != "j_1" {
		t.Fatalf("job %+v, %v", job, err)
	}
}

func TestWithoutAKeyOnlyFindAndGetAreSent(t *testing.T) {
	t.Setenv("CRAWL4AI_API_KEY", "")
	t.Setenv("CRAWL4AI_KEY", "")
	s := fake(t, answerJSON(200, map[string]any{"tools": []any{}, "id": "scrape"}))
	c, err := NewClient(WithBaseURL(s.url))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := c.Tools.Find(ctx, "amazon", nil); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Tools.Get(ctx, "scrape"); err != nil {
		t.Fatal(err)
	}
	_, err = c.Tools.Run(ctx, "scrape", map[string]any{}, nil)
	isKind(t, err, ErrAuthentication)
	_, err = c.Tools.Estimate(ctx, "scrape", map[string]any{})
	isKind(t, err, ErrAuthentication)
	_, err = c.Tools.Batch(ctx, "scrape", nil)
	isKind(t, err, ErrAuthentication)
	got := s.got()
	if len(got) != 2 || got[0].header.Get("Authorization") != "" || got[1].header.Get("Authorization") != "" {
		t.Fatalf("sent %+v", got)
	}
}

func TestAToolIDIsEscapedAndAFolderStepIsRefused(t *testing.T) {
	s := fake(t, answerJSON(200, map[string]any{"id": "a/b"}))
	if _, err := s.client.Tools.Get(ctx, "a/b"); err != nil || s.got()[0].path != "/tools/a%2Fb" {
		t.Fatalf("path %v, %v", s.got(), err)
	}
	for _, id := range []string{"", ".", ".."} {
		_, err := s.client.Tools.Get(ctx, id)
		isKind(t, err, ErrBadRequest)
	}
}

func TestErrorDetailsThatAreNotObjectsDoNotPanic(t *testing.T) {
	e := errorFrom(422, []byte(`{"error":"invalid_input","details":[null,"x",{"problem":"url is required"}]}`))
	if e.Message != "invalid_input: url is required" {
		t.Fatalf("message %q", e.Message)
	}
}
