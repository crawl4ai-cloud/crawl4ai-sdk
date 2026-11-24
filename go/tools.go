package crawl4ai

import (
	"context"
	"net/http"
	"net/url"
	"strconv"
)

// Tools is the Toolkit, reached as client.Tools: every Crawl4AI tool, called the same way.
//
// A tool is one kind of data: `scrape`, `search` and `extract` work on any website, and a ready tool
// exists for each supported site (`amazon-product`, `linkedin-company`, ...). Find one with Find,
// read its inputs with Get, price a run with Estimate, run it with Run, or run it on many inputs as
// one job with Batch.
//
//	run, err := client.Tools.Run(ctx, "amazon-product", map[string]any{"product": "B0F5HSNDXF"}, nil)
//	if err != nil {
//		return err
//	}
//	fmt.Println(run.Rows)
type Tools struct {
	c *Client
}

// FindToolsOptions are the options of Tools.Find. An empty field is left out.
type FindToolsOptions struct {
	Kind      string // `pages`, `search`, `people` or `sites`
	Source    string // one site, for example `amazon`
	Status    string // `verified`, `beta` or `failing`
	Essential bool   // only the tools that work on any website
	Limit     int    // tools per page: 50 when zero, at most 200
	Cursor    string // NextCursor of the last page
}

// Find lists the tools, best match for q first (GET /tools). Free, and works without a key. Every
// word of q must be in the tool's id, name, site, summary or search words. opts may be nil.
//
//	list, err := client.Tools.Find(ctx, "amazon", nil)
//	if err != nil {
//		return err
//	}
//	for _, tool := range list.Tools {
//		fmt.Println(tool.ID, tool.Cost, tool.Summary)
//	}
func (t *Tools) Find(ctx context.Context, q string, opts *FindToolsOptions) (*ToolList, error) {
	query := url.Values{}
	if q != "" {
		query.Set("q", q)
	}
	if opts != nil {
		for name, value := range map[string]string{"kind": opts.Kind, "source": opts.Source, "status": opts.Status, "cursor": opts.Cursor} {
			if value != "" {
				query.Set(name, value)
			}
		}
		if opts.Essential {
			query.Set("essential", "true")
		}
		if opts.Limit != 0 {
			query.Set("limit", strconv.Itoa(opts.Limit))
		}
	}
	return do[ToolList](ctx, t.c, call{method: "GET", path: "/tools", query: query, keyless: true})
}

// Get returns one tool in full: its Inputs, Output, Cost, Examples and InputSchema (GET /tools/{id}).
// Free, and works without a key. An unknown id is an ErrNotFound error; its Body["did_you_mean"]
// lists the closest ids.
//
//	tool, err := client.Tools.Get(ctx, "amazon-product")
//	if err != nil {
//		return err
//	}
//	for _, input := range tool.Inputs {
//		fmt.Println(input.Name, input.Required)
//	}
func (t *Tools) Get(ctx context.Context, toolID string) (*Tool, error) {
	path, err := toolPath(toolID, "")
	if err != nil {
		return nil, err
	}
	return do[Tool](ctx, t.c, call{method: "GET", path: path, keyless: true})
}

// Estimate says what a run with these inputs would cost, before it runs (POST /tools/{id}/estimate). Free.
//
//	est, err := client.Tools.Estimate(ctx, "amazon-product", map[string]any{"product": "B0F5HSNDXF"})
//	if err != nil {
//		return err
//	}
//	fmt.Println(est.Data["text"])
func (t *Tools) Estimate(ctx context.Context, toolID string, inputs map[string]any) (*ToolEstimate, error) {
	path, err := toolPath(toolID, "/estimate")
	if err != nil {
		return nil, err
	}
	return do[ToolEstimate](ctx, t.c, call{method: "POST", path: path, body: inputs})
}

// RunToolOptions are the options of Tools.Run. Fresh skips the cache, at the live price.
type RunToolOptions struct {
	Fresh bool
}

// Run runs a tool on your key, at the price of the tool's own address (POST /tools/{id}).
//
// A tool that returns rows puts them in Rows; the rest of its answer is in Data. A failed run is not
// charged. The call is never sent twice after a 500 or a lost connection, since it may already have
// run and been charged. Errors: ErrBadRequest (`invalid_input`, the problem in Message),
// ErrNotFound (`tool_not_found`) and ErrServer (`tool_failing`: the tool's daily check is failing;
// not retried). opts may be nil.
//
//	run, err := client.Tools.Run(ctx, "scrape", map[string]any{"url": "https://example.com"}, nil)
//	if err != nil {
//		return err
//	}
//	fmt.Println(string(run.Data))
func (t *Tools) Run(ctx context.Context, toolID string, inputs map[string]any, opts *RunToolOptions) (*ToolRun, error) {
	path, err := toolPath(toolID, "")
	if err != nil {
		return nil, err
	}
	var header http.Header
	if opts != nil && opts.Fresh {
		header = http.Header{"Crawl4AI-Fresh": {"true"}}
	}
	return do[ToolRun](ctx, t.c, call{method: "POST", path: path, body: inputs, header: header, once: true})
}

// Batch runs a tool on many inputs as one background job and returns at once (POST /tools/batch).
// The job is in Data: unmarshal it into a ScrapeJob, wait for it with WaitScrapeJob, then read it
// with GetScrapeJobResults. A tool with no batch is an ErrBadRequest error. Never sent twice after a
// 500 or a lost connection, so a job is never started twice.
//
//	run, err := client.Tools.Batch(ctx, "scrape", []map[string]any{{"url": "https://example.com"}, {"url": "https://example.org"}})
//	if err != nil {
//		return err
//	}
//	var job crawl4ai.ScrapeJob
//	if err := json.Unmarshal(run.Data, &job); err != nil {
//		return err
//	}
//	_, err = client.WaitScrapeJob(ctx, job.JobID, nil)
func (t *Tools) Batch(ctx context.Context, toolID string, inputs []map[string]any) (*ToolRun, error) {
	body := map[string]any{"tool": toolID, "inputs": inputs}
	return do[ToolRun](ctx, t.c, call{method: "POST", path: "/tools/batch", body: body, once: true})
}
