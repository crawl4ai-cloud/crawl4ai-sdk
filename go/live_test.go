// Live tests against the real API. They run only when CRAWL4AI_API_KEY is set, and they spend a few
// credits. CRAWL4AI_BASE_URL points them at another address.

package crawl4ai

import (
	"os"
	"testing"
	"time"
)

func live(t *testing.T) *Client {
	t.Helper()
	if os.Getenv("CRAWL4AI_API_KEY") == "" {
		t.Skip("CRAWL4AI_API_KEY is not set")
	}
	opts := []Option{}
	if base := os.Getenv("CRAWL4AI_BASE_URL"); base != "" {
		opts = append(opts, WithBaseURL(base))
	}
	c, err := NewClient(opts...)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestLiveScrape(t *testing.T) {
	p, err := live(t).Scrape(ctx, "https://example.com", &ScrapeOptions{Format: "md"})
	if err != nil || !p.OK || p.Markdown == "" {
		t.Fatalf("%+v %v", p, err)
	}
}

func TestLiveScrapeBatch(t *testing.T) {
	var items []ScrapeBatchItem
	for item, err := range live(t).ScrapeBatch(ctx, []string{"https://example.com"}, &ScrapeOptions{Format: "md"}) {
		if err != nil {
			t.Fatal(err)
		}
		items = append(items, item)
	}
	if len(items) != 1 || !items[0].OK || items[0].Result.Markdown == "" {
		t.Fatalf("%+v", items)
	}
}

func TestLiveScrapeJob(t *testing.T) {
	c := live(t)
	job, err := c.StartScrapeJob(ctx, []string{"https://example.com"}, &ScrapeOptions{Format: "md"})
	if err != nil || job.JobID == "" {
		t.Fatalf("%+v %v", job, err)
	}
	if job, err = c.WaitScrapeJob(ctx, job.JobID, &WaitOptions{PollInterval: time.Second, Timeout: 5 * time.Minute}); err != nil || job.Status != "done" {
		t.Fatalf("%+v %v", job, err)
	}
	var items []ScrapeJobItem
	for item, err := range c.GetScrapeJobResults(ctx, job.JobID) {
		if err != nil {
			t.Fatal(err)
		}
		items = append(items, item)
	}
	if len(items) != 1 || items[0].URL != "https://example.com" || !items[0].OK {
		t.Fatalf("%+v", items)
	}
}

func TestLiveSearch(t *testing.T) {
	r, err := live(t).Search(ctx, "example domain", nil)
	if err != nil || len(r.Results) == 0 {
		t.Fatalf("%+v %v", r, err)
	}
}

func TestLiveSerp(t *testing.T) {
	if _, err := live(t).Serp(ctx, "example domain", nil); err != nil {
		t.Fatal(err)
	}
}

func TestLiveAnswerWithASchema(t *testing.T) {
	schema := map[string]any{"type": "object", "properties": map[string]any{"city": map[string]any{"type": "string"}}}
	if _, err := live(t).Answer(ctx, "What is the capital of France?", &AnswerOptions{Schema: schema}); err != nil {
		t.Fatal(err)
	}
}

func TestLiveExtract(t *testing.T) {
	r, err := live(t).Extract(ctx, &ExtractOptions{Content: "<h1>Hello</h1><p>Price: $5</p>", Instruction: "the price"})
	if err != nil || !r.OK {
		t.Fatalf("%+v %v", r, err)
	}
}
