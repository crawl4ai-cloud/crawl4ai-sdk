/**
 * The client: `Crawl4AI`. Every method sends its call through `#open`, which adds the headers,
 * retries what is worth retrying and turns an error answer into an error (the shared rules are in
 * `http.ts`).
 */

import { APIConnectionError, APITimeoutError } from "./errors.js";
import * as http from "./http.js";
import type {
  AnswerResult,
  ExtractResult,
  ScrapeBatchItem,
  ScrapeJob,
  ScrapeJobItem,
  ScrapeJobRetry,
  ScrapeOptions,
  ScrapeResult,
  SearchResult,
  SerpResult,
  Tool,
  ToolEstimate,
  ToolList,
  ToolRun,
} from "./types.js";

// a job's status once it no longer changes by itself
const JOB_STOPPED = ["done", "paused"];

export interface ClientOptions {
  /**
   * Your key; when not given it is read from `CRAWL4AI_API_KEY`. Without one only `tools.find`
   * and `tools.get` work; every other call throws AuthenticationError.
   */
  apiKey?: string;
  /** The API address. */
  baseUrl?: string;
  /** Milliseconds to wait for an answer, and between two parts of a streamed answer. */
  timeout?: number;
  /** How many times a busy or rate-limited call is sent again. */
  maxRetries?: number;
  /** Your own `fetch` (for a proxy, say). */
  fetch?: typeof fetch;
}

interface Call {
  query?: Record<string, unknown>;
  json?: Record<string, unknown>;
  headers?: Record<string, string>;
  /** false for a free call whose answer has fields of its own named like the cost headers (a tool's `cost`). */
  costs?: boolean;
  /** false for a call that must never run twice: it is not retried after a 500 or a lost connection. */
  safe?: boolean;
  /** true for a free call that is sent even when the client has no key. */
  keyless?: boolean;
}

/**
 * Aborts a request after `ms` with no progress. `touch` starts the count again, `stop` ends it,
 * and `expired` says whether it fired.
 */
function idleTimer(ms: number) {
  const controller = new AbortController();
  let handle: ReturnType<typeof setTimeout> | undefined;
  const timer = {
    signal: controller.signal,
    expired: false,
    touch() {
      clearTimeout(handle);
      handle = setTimeout(() => {
        timer.expired = true;
        controller.abort();
      }, ms);
    },
    stop() {
      clearTimeout(handle);
    },
  };
  timer.touch();
  return timer;
}

type IdleTimer = ReturnType<typeof idleTimer>;

/** Parses JSON from the server; an answer that is not JSON (a proxy's HTML page, say) throws APIConnectionError. */
function parse(text: string, path: string): Record<string, unknown> {
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new APIConnectionError(`${path}: the answer is not JSON: ${text.slice(0, 100)}`, { cause: e });
  }
}

/** The options of `tools.find`. An option left out is not sent. */
export interface FindToolsOptions {
  /** `pages`, `search`, `people` or `sites`. */
  kind?: "pages" | "search" | "people" | "sites" | (string & {});
  /** One site, for example `amazon`. */
  source?: string;
  /** `verified`, `beta` or `failing`. */
  status?: "verified" | "beta" | "failing" | (string & {});
  /** true for the tools that work on any website. */
  essential?: boolean;
  /** Tools per page: 50 by default, at most 200. */
  limit?: number;
  /** `next_cursor` of the last page. */
  cursor?: string;
}

/**
 * The Toolkit, reached as `client.tools`: every Crawl4AI tool, called the same way.
 *
 * A tool is one kind of data: `scrape`, `search` and `extract` work on any website, and a ready
 * tool exists for each supported site (`amazon-product`, `linkedin-company`, ...). Find one with
 * `find`, read its inputs with `get`, price a run with `estimate`, run it with `run`, or run it on
 * many inputs as one job with `batch`.
 *
 * Example:
 *   import { Crawl4AI } from "crawl4ai-cloud";
 *
 *   const client = new Crawl4AI();
 *   const [tool] = (await client.tools.find("amazon product")).tools;
 *   console.log((await client.tools.run(tool.id, { product: "B0F5HSNDXF" })).rows);
 */
export interface Tools {
  /**
   * Lists the tools, best match for `q` first (`GET /tools`). Free, and works without a key.
   * Every word of `q` must be in the tool's id, name, site, summary or search words.
   *
   * Example:
   *   const { tools } = await new Crawl4AI().tools.find("amazon");
   *   for (const tool of tools) console.log(tool.id, tool.cost, tool.summary);
   */
  find(q?: string, options?: FindToolsOptions): Promise<ToolList>;
  /**
   * One tool in full: its `inputs`, `output`, `cost`, `examples` and `input_schema` (`GET /tools/{id}`).
   * Free, and works without a key. An unknown id throws NotFoundError; its `body.did_you_mean` lists the closest ids.
   *
   * Example:
   *   const tool = await new Crawl4AI().tools.get("amazon-product");
   *   console.log(tool.inputs?.map((input) => input.name));
   */
  get(toolId: string): Promise<Tool>;
  /**
   * What a run with these `inputs` would cost, before it runs (`POST /tools/{id}/estimate`). Free.
   *
   * Example:
   *   console.log((await new Crawl4AI().tools.estimate("amazon-product", { product: "B0F5HSNDXF" })).data?.text);
   */
  estimate(toolId: string, inputs: Record<string, unknown>): Promise<ToolEstimate>;
  /**
   * Runs a tool on your key, at the price of the tool's own address (`POST /tools/{id}`).
   *
   * A tool that returns rows puts them in `rows`; the rest of its answer is in `data`. A failed run
   * is not charged. The call is never sent twice after a 500 or a lost connection, since it may
   * already have run and been charged. `fresh: true` skips the cache, at the live price.
   *
   * Throws BadRequestError (`invalid_input`, the problem in the message), NotFoundError
   * (`tool_not_found`) and ServerError (`tool_failing`: the tool's daily check is failing; not retried).
   *
   * Example:
   *   const run = await new Crawl4AI().tools.run("scrape", { url: "https://example.com" });
   *   console.log(run.data, run.usage);
   */
  run(toolId: string, inputs: Record<string, unknown>, options?: { fresh?: boolean }): Promise<ToolRun>;
  /**
   * Runs a tool on many inputs as one background job and returns at once (`POST /tools/batch`).
   * The job is in `data`: wait for it with `waitScrapeJob` on `data.job_id`, then read it with
   * `getScrapeJobResults`. A tool with no batch throws BadRequestError. Never sent twice after a
   * 500 or a lost connection, so a job is never started twice.
   *
   * Example:
   *   const client = new Crawl4AI();
   *   const run = await client.tools.batch("scrape", [{ url: "https://example.com" }, { url: "https://example.org" }]);
   *   const { job_id: jobId } = run.data as { job_id: string };
   *   await client.waitScrapeJob(jobId);
   *   for await (const item of client.getScrapeJobResults(jobId)) console.log(item.url, item.ok);
   */
  batch(toolId: string, inputs: Record<string, unknown>[]): Promise<ToolRun>;
}

/**
 * The Crawl4AI Cloud client. Every method is one API call and returns a Promise of its answer;
 * `scrapeBatch` and `getScrapeJobResults` are async iterators.
 *
 * Example:
 *   import { Crawl4AI } from "crawl4ai-cloud";
 *
 *   const client = new Crawl4AI();
 *   const page = await client.scrape("https://example.com");
 *   console.log(page.markdown);
 */
export class Crawl4AI {
  readonly #headers: Record<string, string>;
  readonly #baseUrl: string;
  readonly #timeout: number;
  readonly #maxRetries: number;
  readonly #fetch: typeof fetch;

  constructor(options: ClientOptions = {}) {
    this.#headers = http.headers(options.apiKey);
    this.#baseUrl = (options.baseUrl ?? http.BASE_URL).replace(/\/+$/, "");
    this.#timeout = options.timeout ?? http.TIMEOUT;
    this.#maxRetries = options.maxRetries ?? http.MAX_RETRIES;
    // called as a plain function: a browser's fetch throws "Illegal invocation" when it is a method of the client
    this.#fetch = options.fetch ?? ((input, init) => globalThis.fetch(input, init));
    this.tools = {
      find: async (q, options = {}) =>
        this.#json("GET", "/tools", {
          query: { q, ...options, essential: options.essential ? "true" : undefined },
          costs: false,
          keyless: true,
        }),
      get: async (toolId) => this.#json("GET", http.toolPath(toolId), { costs: false, keyless: true }),
      estimate: async (toolId, inputs) =>
        this.#json("POST", http.toolPath(toolId, "/estimate"), { json: inputs, costs: false }),
      run: async (toolId, inputs, options = {}) =>
        this.#json("POST", http.toolPath(toolId), {
          json: inputs,
          headers: options.fresh ? { "Crawl4AI-Fresh": "true" } : {},
          safe: false,
        }),
      batch: async (toolId, inputs) =>
        this.#json("POST", "/tools/batch", { json: { tool: toolId, inputs }, safe: false }),
    };
  }

  /** The Toolkit: every Crawl4AI tool, called the same way. See `Tools`. */
  readonly tools: Tools;

  /**
   * Sends one request and returns the success answer with its running timer, or throws.
   *
   * 1. Send. A network failure is retried only when `safe`; a timeout is never retried
   *    (the server may still be working on it).
   * 2. On 429 / 503 (and 500 / 504 when `safe`) wait `retryDelay` and send again,
   *    up to `maxRetries` times.
   * 3. Any other error answer throws the error `errorFrom` picks.
   * The caller reads the body and then stops the timer. Without a key only a `keyless` call is
   * sent; any other throws AuthenticationError.
   */
  async #open(method: string, path: string, call: Call = {}): Promise<{ response: Response; timer: IdleTimer }> {
    const { query, json, safe = true } = call;
    if (!call.keyless) http.requireKey(this.#headers);
    const url = this.#baseUrl + path + http.query(query ?? {});
    const headers = { ...this.#headers, ...(json ? { "Content-Type": "application/json" } : {}), ...call.headers };
    for (let attempt = 0; ; attempt++) {
      const last = attempt >= this.#maxRetries;
      const timer = idleTimer(this.#timeout);
      // ---- 1. Send ----
      let response: Response;
      try {
        response = await this.#fetch(url, {
          method,
          headers,
          body: json ? JSON.stringify(json) : undefined,
          signal: timer.signal,
        });
      } catch (e) {
        timer.stop();
        if (timer.expired) throw new APITimeoutError(`No answer from ${path} in time`, { cause: e });
        if (last || !safe) throw new APIConnectionError(`${path}: ${String(e)}`, { cause: e });
        await http.clock.sleep(http.retryDelay(attempt));
        continue;
      }
      if (response.ok) return { response, timer };
      // ---- 2. Retry ----
      const text = await response.text().catch(() => "");
      timer.stop();
      const error = http.errorFrom(response.status, text);
      if (last || !http.shouldRetry(error, safe)) {
        // ---- 3. Throw ----
        throw error;
      }
      await http.clock.sleep(http.retryDelay(attempt, response.headers.get("retry-after")));
    }
  }

  /** Sends one request and returns its JSON answer with the cost headers added (unless `costs: false`). */
  async #json<T>(method: string, path: string, call?: Call): Promise<T> {
    const { response, timer } = await this.#open(method, path, call);
    let text: string;
    try {
      text = await response.text();
    } catch (e) {
      throw timer.expired
        ? new APITimeoutError(`${path}: the answer stopped coming in time`, { cause: e })
        : new APIConnectionError(`${path}: the answer stopped: ${String(e)}`, { cause: e });
    } finally {
      timer.stop();
    }
    return { ...parse(text, path), ...(call?.costs === false ? {} : http.costs(response)) } as T;
  }

  /** Sends one request and yields each line of its NDJSON answer as an object, as it arrives. */
  async *#lines(method: string, path: string, call?: Call): AsyncGenerator<Record<string, unknown>> {
    const { response, timer } = await this.#open(method, path, call);
    if (!response.body) return timer.stop();
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    try {
      for (;;) {
        let chunk: ReadableStreamReadResult<string>;
        try {
          chunk = await reader.read();
        } catch (e) {
          throw timer.expired
            ? new APITimeoutError(`${path}: the answer stopped coming in time`, { cause: e })
            : new APIConnectionError(`${path}: the answer stopped: ${String(e)}`, { cause: e });
        }
        if (chunk.done) break;
        buffer += chunk.value;
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        timer.stop(); // the caller's own time between lines does not count against the server
        for (const line of lines) if (line.trim()) yield parse(line, path);
        timer.touch();
      }
      timer.stop();
      if (buffer.trim()) yield parse(buffer, path);
    } finally {
      timer.stop();
      reader.cancel().catch(() => {});
    }
  }

  /**
   * Fetches one page and returns it as clean Markdown and/or HTML (`POST /scrape`).
   *
   * Most pages take 1 to 2 s; a page that needs a real browser takes up to 90 s.
   * A site that refuses every attempt throws BlockedError (`code` `blocked` or `login-wall`).
   *
   * Options: `format`, `proxy`, `country`, `parse`, `engine` (see `ScrapeOptions`), and
   * `bypassCache`: true to always fetch the page fresh, never from a cached copy.
   *
   * Example:
   *   import { Crawl4AI } from "crawl4ai-cloud";
   *
   *   const page = await new Crawl4AI().scrape("https://example.com", { format: "md" });
   *   console.log(page.markdown);
   */
  scrape(url: string, options: ScrapeOptions & { bypassCache?: boolean } = {}): Promise<ScrapeResult> {
    const { bypassCache, ...rest } = options;
    return this.#json("POST", "/scrape", { json: http.body({ url, ...rest, bypass_cache: bypassCache }) });
  }

  /**
   * Scrapes up to 50 URLs in one call and yields each one as soon as it is ready
   * (`POST /scrape/batch`), in the order they finish. Each item has its own `cost`.
   *
   * Example:
   *   import { Crawl4AI } from "crawl4ai-cloud";
   *
   *   for await (const item of new Crawl4AI().scrapeBatch(["https://example.com", "https://example.org"])) {
   *     console.log(item.url, item.ok ? item.result?.markdown?.slice(0, 80) : item.error);
   *   }
   */
  async *scrapeBatch(urls: string[], options: ScrapeOptions = {}): AsyncGenerator<ScrapeBatchItem> {
    for await (const line of this.#lines("POST", "/scrape/batch", { json: http.body({ urls, ...options }) })) {
      if ("summary" in line) continue; // the last line totals the batch; each item has its own cost
      const item = line as unknown as ScrapeBatchItem;
      yield item.cost == null ? item : { ...item, cost: Number(item.cost) };
    }
  }

  /**
   * Starts a background job for up to 10,000 URLs and returns at once with its `job_id`
   * (`POST /scrape/jobs`). Then `waitScrapeJob` and `getScrapeJobResults`.
   *
   * Every URL is charged the job's flat price; URLs that never got an answer are refunded
   * when the job ends. Not retried on a 500, so a job is never started twice.
   *
   * Example:
   *   import { Crawl4AI } from "crawl4ai-cloud";
   *
   *   const client = new Crawl4AI();
   *   const job = await client.startScrapeJob(["https://example.com", "https://example.org"]);
   *   await client.waitScrapeJob(job.job_id);
   *   for await (const item of client.getScrapeJobResults(job.job_id)) console.log(item.url, item.ok);
   */
  startScrapeJob(urls: string[], options: ScrapeOptions = {}): Promise<ScrapeJob> {
    return this.#json("POST", "/scrape/jobs", { json: http.body({ urls, ...options }), safe: false });
  }

  /**
   * Returns a job's `status`, `counts` and `usage` (`GET /scrape/jobs/{id}`).
   * `full: true` adds every URL's detail.
   *
   * Example:
   *   import { Crawl4AI } from "crawl4ai-cloud";
   *
   *   const client = new Crawl4AI();
   *   const job = await client.startScrapeJob(["https://example.com"]);
   *   console.log((await client.getScrapeJob(job.job_id)).status);
   */
  async getScrapeJob(jobId: string, options: { full?: boolean } = {}): Promise<ScrapeJob> {
    return this.#json("GET", http.jobPath(jobId), { query: options });
  }

  /**
   * Checks the job every `pollInterval` ms (default 2000) and returns it once its status is `done`
   * (or `paused`, which needs you to act). Throws APITimeoutError after `timeout` ms.
   *
   * Example:
   *   import { Crawl4AI } from "crawl4ai-cloud";
   *
   *   const client = new Crawl4AI();
   *   const job = await client.startScrapeJob(["https://example.com"]);
   *   console.log((await client.waitScrapeJob(job.job_id, { timeout: 600_000 })).counts);
   */
  async waitScrapeJob(jobId: string, options: { pollInterval?: number; timeout?: number } = {}): Promise<ScrapeJob> {
    const { pollInterval = 2000, timeout } = options;
    const deadline = timeout == null ? undefined : Date.now() + timeout;
    for (;;) {
      const job = await this.getScrapeJob(jobId);
      if (JOB_STOPPED.includes(job.status)) return job;
      const left = deadline == null ? pollInterval : deadline - Date.now();
      if (left <= 0) throw new APITimeoutError(`Job ${jobId} is still ${job.status} after ${timeout} ms`);
      await http.clock.sleep(Math.min(pollInterval, left));
    }
  }

  /**
   * Yields a job's results, one item per URL, fetching page after page for you
   * (`GET /scrape/jobs/{id}/results`). Read them after `waitScrapeJob`.
   *
   * Example:
   *   import { Crawl4AI } from "crawl4ai-cloud";
   *
   *   const client = new Crawl4AI();
   *   const job = await client.startScrapeJob(["https://example.com"]);
   *   await client.waitScrapeJob(job.job_id);
   *   for await (const item of client.getScrapeJobResults(job.job_id)) {
   *     console.log(item.url, item.ok ? item.markdown?.slice(0, 80) : item.error);
   *   }
   */
  async *getScrapeJobResults(jobId: string): AsyncGenerator<ScrapeJobItem> {
    const path = http.jobPath(jobId, "/results");
    for (let after = 0; ; ) {
      let read = 0;
      for await (const line of this.#lines("GET", path, { query: { after } })) {
        read++;
        yield line as unknown as ScrapeJobItem;
      }
      if (read === 0) return; // an empty page: no more results
      after += read;
    }
  }

  /**
   * Runs a job's failed URLs again (`POST /scrape/jobs/{id}/retry`); `retrying` says how many.
   *
   * Example:
   *   import { Crawl4AI } from "crawl4ai-cloud";
   *
   *   const client = new Crawl4AI();
   *   const job = await client.startScrapeJob(["https://example.com"]);
   *   await client.waitScrapeJob(job.job_id);
   *   console.log((await client.retryScrapeJob(job.job_id)).retrying);
   */
  async retryScrapeJob(jobId: string): Promise<ScrapeJobRetry> {
    return this.#json("POST", http.jobPath(jobId, "/retry"), { safe: false });
  }

  /**
   * Searches the web and returns ranked, cleaned results (`GET /search`).
   *
   * `q` is the query, at most 512 characters. `rich: true` adds follow-up questions, related
   * queries, an entity card, videos and news. `deep: true` also reads the top 10 pages and puts
   * each page's text in its result's `markdown`: up to 5 s slower, and each page with text costs
   * one plain scrape page.
   *
   * Example:
   *   import { Crawl4AI } from "crawl4ai-cloud";
   *
   *   const { results } = await new Crawl4AI().search("rust web crawler");
   *   for (const result of results) console.log(result.title, result.url);
   */
  search(q: string, options: { rich?: boolean; deep?: boolean } = {}): Promise<SearchResult> {
    return this.#json("GET", "/search", { query: { q, ...options } });
  }

  /**
   * Returns Google's results page as data: true ranks and every block Google showed
   * (`GET /serp`, beta).
   *
   * Options:
   *   `country`, `language`: the Google page's country (`us`) and language (`en`).
   *   `location`: a city or region, for example `Austin, TX`.
   *   `num`: results per page, 10 to 100 in steps of 10. `page`: which page, in steps of `num`.
   *   `time`: only results from the past hour, day, week, month or year.
   *   `fresh`: true skips the cache, at the live price.
   *   `source`: `google` for the road that also returns the AI Overview.
   *
   * Example:
   *   import { Crawl4AI } from "crawl4ai-cloud";
   *
   *   const { results } = await new Crawl4AI().serp("best crm software", { country: "us" });
   *   for (const result of results) console.log(result.position, result.domain);
   */
  serp(
    q: string,
    options: {
      country?: string;
      language?: string;
      location?: string;
      num?: number;
      page?: number;
      time?: "hour" | "day" | "week" | "month" | "year" | (string & {});
      fresh?: boolean;
      source?: "auto" | "google" | (string & {});
    } = {},
  ): Promise<SerpResult> {
    return this.#json("GET", "/serp", { query: { q, ...options } });
  }

  /**
   * Answers a question from the web, with its sources (`GET /answer`, experimental).
   * When there is no answer, `answered` is false and the call costs nothing.
   *
   * Options:
   *   `schema`: a JSON Schema; `answer.text` is then JSON of that shape (parse it with JSON.parse).
   *   `deep`: false returns only an answer that is readily available, without reading pages.
   *
   * Example:
   *   import { Crawl4AI } from "crawl4ai-cloud";
   *
   *   const result = await new Crawl4AI().answer("why is the sky blue");
   *   if (result.answered) console.log(result.answer?.text);
   */
  answer(q: string, options: { schema?: Record<string, unknown>; deep?: boolean } = {}): Promise<AnswerResult> {
    const schema = options.schema && JSON.stringify(options.schema);
    return this.#json("GET", "/answer", { query: { q, schema, deep: options.deep } });
  }

  /**
   * Pulls structured data out of a page with a language model (`POST /extract`).
   *
   * Give a `url` (the page is fetched for you) or `content` (your own text, Markdown or HTML),
   * plus `instruction` (what to pull out, in plain English) and/or `schema` (a JSON Schema each
   * record must match). `example` is a sample of the shape you want.
   *
   * Example:
   *   import { Crawl4AI } from "crawl4ai-cloud";
   *
   *   const client = new Crawl4AI();
   *   const result = await client.extract("https://news.ycombinator.com", { instruction: "the top 3 story titles" });
   *   console.log(result.data);
   *   const mine = await client.extract({ content: "<p>Price: $5</p>", instruction: "the price" });
   */
  extract(url: string, options?: ExtractOptions): Promise<ExtractResult>;
  extract(options: ExtractOptions & { url?: string; content?: string }): Promise<ExtractResult>;
  extract(
    urlOrOptions: string | (ExtractOptions & { url?: string; content?: string }),
    options: ExtractOptions = {},
  ): Promise<ExtractResult> {
    const fields = typeof urlOrOptions === "string" ? { url: urlOrOptions, ...options } : urlOrOptions;
    return this.#json("POST", "/extract", { json: http.body(fields) });
  }
}

/** What `extract` pulls out: an `instruction`, a `schema`, or both, and an optional `example`. */
export interface ExtractOptions {
  instruction?: string;
  schema?: Record<string, unknown>;
  example?: unknown;
}
