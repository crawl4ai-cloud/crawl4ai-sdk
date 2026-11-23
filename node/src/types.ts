/**
 * The results the SDK returns. Each one is the server's JSON answer as it came, with the API's own
 * field names, so a field the server adds later is never lost. A field the server did not send is
 * undefined.
 */

/** The options every scrape call takes. */
export interface ScrapeOptions {
  /** `both` (the default), `md` or `html`. */
  format?: "both" | "md" | "html" | (string & {});
  /** `extra` tries harder when a site refuses; such a page costs 4x. */
  proxy?: "standard" | "extra" | (string & {});
  /** Two letters, the country the page is fetched from (`us`, `gb`). */
  country?: string;
  /** true for the page's links, media, metadata and tables, or pick some: `{ links: true }`. */
  parse?: boolean | { links?: boolean; media?: boolean; metadata?: boolean; tables?: boolean };
  /** `browser-light` or `browser` to start at a browser; use only when the default misses content. */
  engine?: "auto" | "browser-light" | "browser" | (string & {});
}

/**
 * A whole answer to one call, with the cost headers: credits this call cost (`cost`), credits left
 * on the account (`balance`) and credits left under this month's plan (`allowance_left`).
 */
export interface Costs {
  cost?: number;
  balance?: number;
  allowance_left?: number;
}

/** A page someone can open: its `title` and `url`. */
export interface Link {
  title?: string;
  url?: string;
}

/** One page from `scrape`. `markdown` and `html` are set by the `format` you asked for. */
export interface ScrapeResult extends Costs {
  ok: boolean;
  markdown?: string;
  html?: string;
  engine?: string;
  cache?: string;
  reason?: string;
  ms?: number;
  bytes?: number;
  text_len?: number;
  content_hash?: string;
  exit?: string;
  ladder?: Array<Record<string, unknown>>;
  usage?: Record<string, unknown>;
}

/**
 * One URL's line from `scrapeBatch`: the page in `result` when `ok`, else the reason in `error`.
 * `cost` is what this URL cost, in credits (the server sends it as text; it becomes a number).
 */
export interface ScrapeBatchItem {
  url: string;
  ok: boolean;
  result?: ScrapeResult;
  error?: string;
  cost?: number;
  effort?: number;
}

/**
 * A background scrape job. `status` is `pending`, `running`, `done` or `paused`; `counts` holds
 * the number of URLs `pending`, `done` and in `error`; `usage` what the job cost.
 */
export interface ScrapeJob extends Costs {
  job_id: string;
  status: string;
  counts?: { pending?: number; done?: number; error?: number };
  usage?: Record<string, unknown>;
}

/** One URL's line from a job's results. On failure `ok` is false and `error` holds `class` and `detail`. */
export interface ScrapeJobItem {
  url: string;
  ok: boolean;
  markdown?: string;
  html?: string;
  content_hash?: string | null;
  error?: { class?: string; detail?: string } | null;
  seq?: number;
}

/** The answer to `retryScrapeJob`: `retrying` is the number of failed URLs queued again. */
export interface ScrapeJobRetry extends Costs {
  job_id: string;
  retrying: number;
  usage?: Record<string, unknown>;
}

/**
 * One web result. `source` is `gg` or `gs` for a live result, `index` for the Crawl4AI index.
 * `markdown` (only with `deep: true`) is the page's text, absent when the page gave none in time.
 */
export interface SearchItem {
  title?: string;
  url: string;
  snippet?: string;
  source?: string;
  markdown?: string;
}

/**
 * The answer to `search`. `rich` (only with `rich: true`) holds follow-up questions, related
 * queries, an entity card and more, each key only when it was on the page. `deep` and
 * `usage.deep_pages` (only with `deep: true`) count the pages read and the pages charged.
 */
export interface SearchResult extends Costs {
  results: SearchItem[];
  deep?: { launched?: number; got?: number; from_archive?: number; late?: number; ms?: number };
  usage?: { deep_pages?: number };
  rich?: {
    follow_up_questions?: string[];
    related_queries?: string[];
    entity?: { title?: string; subtitle?: string; description?: string; facts?: unknown[] };
    videos?: Link[];
    news?: Link[];
    discussions?: Link[];
    did_you_mean?: string;
  };
}

/** One organic Google result. `position` counts organic results only; `position_absolute` counts every block. */
export interface SerpItem {
  position: number;
  position_absolute?: number;
  title?: string;
  url: string;
  domain?: string;
  displayed_url?: string;
  snippet?: string;
  date?: string;
  sitelinks?: Link[];
}

/**
 * The answer to `serp`: Google's results page. `blocks` names every block on the page in order;
 * each block that was on the page is a field of its own (`knowledge_panel`, `local_pack`, ...).
 */
export interface SerpResult extends Costs {
  search?: Record<string, unknown>;
  results: SerpItem[];
  blocks?: string[];
  total_results?: number;
  source?: string;
  empty_reason?: string;
  cached?: boolean;
  age_s?: number;
  pages?: { asked?: number; got?: number; missing?: number[] };
  ai_overview?: { text?: string; sources?: Link[] };
  people_also_ask?: string[];
  related_searches?: string[];
  ms?: number;
  [block: string]: unknown;
}

/** The answer `text` (JSON text when a schema was given), who wrote it (`source`) and the pages it drew on. */
export interface Answer {
  text: string;
  source?: string;
  sources?: Link[];
}

/** The answer to `answer`. `answered` is false when there is no direct answer yet. */
export interface AnswerResult extends Costs {
  answered: boolean;
  answer?: Answer;
  query?: string;
  experimental?: boolean;
}

/** The answer to `extract`: the records in `data`, in the shape of your schema when you gave one. */
export interface ExtractResult extends Costs {
  ok: boolean;
  url?: string;
  data?: unknown;
  usage?: Record<string, unknown>;
  ms?: number;
}

/**
 * One tool of the Toolkit. `find` fills the summary fields: `id`, `name` (`[lead word, rest]`),
 * `source` (the site), `kind`, `summary`, `cost` (text like `1 cr`), `typical` (a typical run time),
 * `status`, `essential` and `beta`. `get` adds `description`, `inputs`, `output` (`output.fields`),
 * `examples` and `input_schema` (a JSON Schema of the inputs), and gives `cost` as an object.
 */
export interface Tool {
  id: string;
  name?: string[];
  source?: string;
  kind?: string;
  summary?: string;
  cost?: unknown;
  typical?: string;
  status?: "verified" | "beta" | "failing" | (string & {});
  essential?: boolean;
  beta?: boolean;
  description?: string;
  inputs?: Array<{ name: string; type?: string; required?: boolean; help?: string; example?: unknown } & Record<string, unknown>>;
  output?: { fields?: Array<Record<string, unknown>> } & Record<string, unknown>;
  examples?: Array<{ label?: string; input?: Record<string, unknown> }>;
  input_schema?: Record<string, unknown>;
}

/** The answer to `tools.find`: the `tools` on this page, the `total` that match, and `next_cursor` for the next page. */
export interface ToolList {
  tools: Tool[];
  total?: number;
  next_cursor?: string | null;
  counts?: Record<string, unknown>;
}

/**
 * The answer to `tools.estimate`: `text` says the price in words (`1 cr`) and `rule` how it is set.
 * Some tools give their own estimate in `data` instead (`data.text`, `data.min`, `data.max`).
 */
export interface ToolEstimate {
  tool?: string;
  text?: string;
  rule?: string;
  data?: Record<string, unknown>;
}

/**
 * The answer to `tools.run`, the same shape for every tool: the `rows` it found (a tool that returns
 * rows), the rest of its answer in `data`, `usage.credits`, `took_ms` and the `request_id` to quote
 * when you report a problem.
 */
export interface ToolRun extends Costs {
  tool: string;
  request_id?: string;
  took_ms?: number;
  usage?: { credits?: number | null } & Record<string, unknown>;
  rows?: Array<Record<string, unknown>>;
  data?: unknown;
}
