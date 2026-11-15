package crawl4ai

import "encoding/json"

// The results the client returns use the API's own field names in their JSON tags. Each answer to
// a call also carries Meta: what the call cost and the answer as it came, so a field the server
// adds later is never lost.

// Meta is on every answer to a call: the credits the call cost (Cost), the credits left on the
// account (Balance), the credits left under this month's plan (AllowanceLeft), each nil when the
// server did not send it, and the whole answer as JSON (Raw).
type Meta struct {
	Cost          *float64        `json:"-"`
	Balance       *float64        `json:"-"`
	AllowanceLeft *float64        `json:"-"`
	Raw           json.RawMessage `json:"-"`
}

func (m *Meta) meta() *Meta { return m }

// ScrapeOptions are the options every scrape call takes. An empty field is left out of the request.
type ScrapeOptions struct {
	Format  string `json:"format,omitempty"`  // `both` (the default), `md` or `html`
	Proxy   string `json:"proxy,omitempty"`   // `extra` tries harder when a site refuses; such a page costs 4x
	Country string `json:"country,omitempty"` // two letters, the country the page is fetched from (`us`, `gb`)
	Parse   *Parse `json:"parse,omitempty"`   // the page's links, media, metadata and tables
	Engine  string `json:"engine,omitempty"`  // `browser-light` or `browser` to start at a browser
	// BypassCache always fetches the page fresh, never from a cached copy. Scrape only.
	BypassCache bool `json:"bypass_cache,omitempty"`
}

// Parse picks what to read from the page besides its text. All asks for everything.
type Parse struct {
	All      bool `json:"-"`
	Links    bool `json:"links,omitempty"`
	Media    bool `json:"media,omitempty"`
	Metadata bool `json:"metadata,omitempty"`
	Tables   bool `json:"tables,omitempty"`
}

func (p Parse) MarshalJSON() ([]byte, error) {
	if p.All {
		return []byte("true"), nil
	}
	type fields Parse
	return json.Marshal(fields(p))
}

// Link is a page someone can open.
type Link struct {
	Title string `json:"title,omitempty"`
	URL   string `json:"url,omitempty"`
}

// ScrapeResult is one page. Markdown and HTML are set by the Format you asked for.
type ScrapeResult struct {
	Meta
	OK          bool           `json:"ok"`
	Markdown    string         `json:"markdown,omitempty"`
	HTML        string         `json:"html,omitempty"`
	Engine      string         `json:"engine,omitempty"`
	Cache       string         `json:"cache,omitempty"`
	Reason      string         `json:"reason,omitempty"`
	Ms          int            `json:"ms,omitempty"`
	Bytes       int            `json:"bytes,omitempty"`
	TextLen     int            `json:"text_len,omitempty"`
	ContentHash string         `json:"content_hash,omitempty"`
	Exit        string         `json:"exit,omitempty"`
	Ladder      []LadderStep   `json:"ladder,omitempty"`
	Usage       map[string]any `json:"usage,omitempty"`
}

// LadderStep is one way the server tried to fetch the page.
type LadderStep struct {
	Step    string `json:"step,omitempty"`
	Outcome string `json:"outcome,omitempty"`
	Ms      int    `json:"ms,omitempty"`
}

// ScrapeBatchItem is one URL from ScrapeBatch: the page in Result when OK, else the reason in
// Error. Cost is what this URL cost, in credits (the server sends it as text).
type ScrapeBatchItem struct {
	URL    string        `json:"url"`
	OK     bool          `json:"ok"`
	Result *ScrapeResult `json:"result,omitempty"`
	Error  string        `json:"error,omitempty"`
	Cost   float64       `json:"-"`
	Effort int           `json:"effort,omitempty"`
}

// ScrapeJob is a background scrape job. Status is `pending`, `running`, `done` or `paused`.
type ScrapeJob struct {
	Meta
	JobID  string         `json:"job_id"`
	Status string         `json:"status"`
	Counts JobCounts      `json:"counts"`
	Usage  map[string]any `json:"usage,omitempty"`
}

// JobCounts is the number of a job's URLs not done yet, done, and failed.
type JobCounts struct {
	Pending int `json:"pending"`
	Done    int `json:"done"`
	Error   int `json:"error"`
}

// ScrapeJobItem is one URL from a job's results. On failure OK is false and Error says why.
type ScrapeJobItem struct {
	URL         string    `json:"url"`
	OK          bool      `json:"ok"`
	Markdown    string    `json:"markdown,omitempty"`
	HTML        string    `json:"html,omitempty"`
	ContentHash string    `json:"content_hash,omitempty"`
	Error       *JobError `json:"error,omitempty"`
	Seq         int       `json:"seq,omitempty"`
}

// JobError is why a job's URL failed.
type JobError struct {
	Class  string `json:"class,omitempty"`
	Detail string `json:"detail,omitempty"`
}

// ScrapeJobRetry is the answer to RetryScrapeJob: Retrying is the number of failed URLs queued again.
type ScrapeJobRetry struct {
	Meta
	JobID    string         `json:"job_id"`
	Retrying int            `json:"retrying"`
	Usage    map[string]any `json:"usage,omitempty"`
}

// SearchItem is one web result. Source is `gg` or `gs` for a live result, `index` for the Crawl4AI index.
type SearchItem struct {
	Title   string `json:"title,omitempty"`
	URL     string `json:"url"`
	Snippet string `json:"snippet,omitempty"`
	Source  string `json:"source,omitempty"`
}

// SearchResult is the answer to Search. Rich is set only with SearchOptions.Rich.
type SearchResult struct {
	Meta
	Results []SearchItem `json:"results"`
	Rich    *SearchRich  `json:"rich,omitempty"`
}

// SearchRich holds what the results page showed besides the results, each field only when it was there.
type SearchRich struct {
	FollowUpQuestions []string `json:"follow_up_questions,omitempty"`
	RelatedQueries    []string `json:"related_queries,omitempty"`
	Entity            *Entity  `json:"entity,omitempty"`
	Videos            []Link   `json:"videos,omitempty"`
	News              []Link   `json:"news,omitempty"`
	Discussions       []Link   `json:"discussions,omitempty"`
	DidYouMean        string   `json:"did_you_mean,omitempty"`
}

// Entity is the card about the thing searched for.
type Entity struct {
	Title       string `json:"title,omitempty"`
	Subtitle    string `json:"subtitle,omitempty"`
	Description string `json:"description,omitempty"`
	Facts       []any  `json:"facts,omitempty"`
}

// SerpItem is one organic Google result. Position counts organic results only; PositionAbsolute counts every block.
type SerpItem struct {
	Position         int    `json:"position"`
	PositionAbsolute int    `json:"position_absolute,omitempty"`
	Title            string `json:"title,omitempty"`
	URL              string `json:"url"`
	Domain           string `json:"domain,omitempty"`
	DisplayedURL     string `json:"displayed_url,omitempty"`
	Snippet          string `json:"snippet,omitempty"`
	Date             string `json:"date,omitempty"`
	Sitelinks        []Link `json:"sitelinks,omitempty"`
}

// SerpResult is the answer to Serp: Google's results page. Blocks names every block on the page in
// order; read one with Block.
type SerpResult struct {
	Meta
	Search          map[string]any `json:"search,omitempty"`
	Results         []SerpItem     `json:"results"`
	Blocks          []string       `json:"blocks,omitempty"`
	TotalResults    int64          `json:"total_results,omitempty"`
	Source          string         `json:"source,omitempty"`
	EmptyReason     string         `json:"empty_reason,omitempty"`
	Cached          bool           `json:"cached,omitempty"`
	AgeS            int            `json:"age_s,omitempty"`
	Pages           *SerpPages     `json:"pages,omitempty"`
	AIOverview      *AIOverview    `json:"ai_overview,omitempty"`
	PeopleAlsoAsk   []string       `json:"people_also_ask,omitempty"`
	RelatedSearches []string       `json:"related_searches,omitempty"`
	Ms              int            `json:"ms,omitempty"`
}

// SerpPages says how many Google pages were asked for and fetched, and which are missing.
type SerpPages struct {
	Asked   int   `json:"asked"`
	Got     int   `json:"got"`
	Missing []int `json:"missing,omitempty"`
}

// AIOverview is Google's AI Overview, with its sources.
type AIOverview struct {
	Text    string `json:"text,omitempty"`
	Sources []Link `json:"sources,omitempty"`
}

// Block returns one block of the page by its name in Blocks (`knowledge_panel`, `local_pack`, ...)
// as JSON, or nil when the page did not have it.
func (r *SerpResult) Block(name string) json.RawMessage {
	var all map[string]json.RawMessage
	_ = json.Unmarshal(r.Raw, &all)
	return all[name]
}

// Answer is the answer Text (JSON text when a schema was given), who wrote it (Source) and the
// pages it drew on.
type Answer struct {
	Text    string `json:"text"`
	Source  string `json:"source,omitempty"`
	Sources []Link `json:"sources,omitempty"`
}

// AnswerResult is the answer to Answer. Answered is false when there is no direct answer yet.
type AnswerResult struct {
	Meta
	Answered     bool    `json:"answered"`
	Answer       *Answer `json:"answer,omitempty"`
	Query        string  `json:"query,omitempty"`
	Experimental bool    `json:"experimental,omitempty"`
}

// ExtractResult is the answer to Extract: the records in Data, in the shape of your schema when you
// gave one. Unmarshal Data into your own type.
type ExtractResult struct {
	Meta
	OK    bool            `json:"ok"`
	URL   string          `json:"url,omitempty"`
	Data  json.RawMessage `json:"data,omitempty"`
	Usage map[string]any  `json:"usage,omitempty"`
	Ms    int             `json:"ms,omitempty"`
}
