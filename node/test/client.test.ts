// Unit tests against a fake fetch: no key, no network, no cost. They run on the built package.

import assert from "node:assert/strict";
import { afterEach, beforeEach, mock, test } from "node:test";

import {
  APIConnectionError,
  APITimeoutError,
  AuthenticationError,
  BadRequestError,
  BlockedError,
  Crawl4AI,
  type Crawl4AIError,
  NotFoundError,
  PaymentRequiredError,
  RateLimitError,
  type ScrapeBatchItem,
  type ScrapeJobItem,
  ServerError,
} from "../dist/index.js";
import { clock } from "../dist/http.js";

const PAGE = { ok: true, markdown: "# Hi", engine: "archive", ms: 4, text_len: 2, new_field: 1 };

interface Sent {
  url: URL;
  method: string;
  headers: Record<string, string>;
  json?: unknown;
}

let waits: number[] = [];

beforeEach(() => {
  // Retries and polling do not wait in tests; the waits are recorded instead.
  waits = [];
  mock.method(clock, "sleep", async (ms: number) => {
    waits.push(ms);
  });
  delete process.env.CRAWL4AI_API_KEY;
  delete process.env.CRAWL4AI_KEY;
});

afterEach(() => mock.restoreAll());

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers });
}

function ndjson(...lines: unknown[]): Response {
  return new Response(lines.map((line) => JSON.stringify(line)).join("\n") + "\n");
}

/** Reads an async iterator to the end. */
async function collect<T>(items: AsyncIterable<T>): Promise<T[]> {
  const all: T[] = [];
  for await (const item of items) all.push(item);
  return all;
}

/** Returns a client that gets `answers` in order, one per request, and the list of what it sent. */
function fake(...answers: Response[]): { client: Crawl4AI; sent: Sent[] } {
  const sent: Sent[] = [];
  const fetch = async (url: string | URL | Request, init?: RequestInit) => {
    const body = init?.body;
    sent.push({
      url: new URL(String(url)),
      method: init?.method ?? "GET",
      headers: init?.headers as Record<string, string>,
      json: typeof body === "string" ? JSON.parse(body) : undefined,
    });
    const answer = answers.shift();
    if (!answer) throw new Error("no answer left");
    return answer;
  };
  return { client: new Crawl4AI({ apiKey: "sk_test", fetch }), sent };
}

test("a missing key throws; the env key is sent, and CRAWL4AI_API_KEY wins", async () => {
  await assert.rejects(new Crawl4AI({ fetch: async () => assert.fail("sent") }).scrape("https://example.com"), AuthenticationError);
  const seen: string[] = [];
  const fetch = async (_url: string | URL | Request, init?: RequestInit) => {
    seen.push((init?.headers as Record<string, string>).Authorization ?? "");
    return json(PAGE);
  };
  process.env.CRAWL4AI_KEY = "sk_old_name";
  await new Crawl4AI({ fetch }).scrape("https://example.com");
  process.env.CRAWL4AI_API_KEY = "sk_new_name";
  await new Crawl4AI({ fetch }).scrape("https://example.com");
  assert.deepEqual(seen, ["Bearer sk_old_name", "Bearer sk_new_name"]);
});

test("a key with a bad character throws without the key; spaces around it are dropped", async () => {
  for (const apiKey of ["sk_live_SEC\nRET", "sk_live_SECRÉT", "sk live"]) {
    assert.throws(() => new Crawl4AI({ apiKey }), (e: Error) => e instanceof AuthenticationError && !e.message.includes("SEC"));
  }
  const { sent } = fake();
  const fetch = async (_url: string | URL | Request, init?: RequestInit) => {
    sent.push({ url: new URL("https://x"), method: "GET", headers: init?.headers as Record<string, string> });
    return json(PAGE);
  };
  await new Crawl4AI({ apiKey: "sk_test\n", fetch }).scrape("https://example.com");
  assert.equal(sent[0]?.headers.Authorization, "Bearer sk_test");
});

test("scrape sends only the fields that are set and reads the result", async () => {
  const { client, sent } = fake(json(PAGE, 200, { "x-c4-cost": "0.500", "x-c4-balance": "99.5" }));
  const page = await client.scrape("https://example.com", { format: "md", parse: { links: true } });

  assert.equal(sent[0]?.method, "POST");
  assert.equal(String(sent[0]?.url), "https://api.crawl4ai.com/scrape");
  assert.equal(sent[0]?.headers.Authorization, "Bearer sk_test");
  assert.deepEqual(sent[0]?.json, { url: "https://example.com", format: "md", parse: { links: true } });
  assert.ok(page.ok && page.markdown === "# Hi" && page.engine === "archive" && page.html === undefined);
  assert.equal(page.cost, 0.5);
  assert.equal(page.balance, 99.5);
  assert.equal(page.allowance_left, undefined);
  assert.equal((page as unknown as Record<string, unknown>).new_field, 1); // a field the SDK does not know is kept
});

test("bypassCache is sent as bypass_cache", async () => {
  const { client, sent } = fake(json(PAGE));
  await client.scrape("https://example.com", { bypassCache: true });
  assert.deepEqual(sent[0]?.json, { url: "https://example.com", bypass_cache: true });
});

test("a value the server adds later can be sent", async () => {
  const { client, sent } = fake(json(PAGE));
  await client.scrape("https://example.com", { engine: "a-new-engine" }); // compiles: the option is an open string
  assert.deepEqual(sent[0]?.json, { url: "https://example.com", engine: "a-new-engine" });
});

test("an answer that is not JSON throws APIConnectionError", async () => {
  const html = () => new Response("<html>proxy login</html>");
  await assert.rejects(fake(html()).client.search("x"), APIConnectionError);
  await assert.rejects(collect(fake(html()).client.scrapeBatch(["https://a.com"])), APIConnectionError);
});

const errorCases: Array<[string, () => Response, new (...args: never[]) => Crawl4AIError, string | undefined]> = [
  ["402", () => json({ error: "no_credit", message: "Out of credits", actions: { subscribe: "u" } }, 402), PaymentRequiredError, "no_credit"],
  ["403 login-wall", () => json({ ok: false, reason: "login-wall" }, 403), BlockedError, "login-wall"],
  ["401 with an empty body", () => new Response(null, { status: 401 }), AuthenticationError, undefined],
  ["422 with plain text", () => new Response("missing field `url`", { status: 422 }), BadRequestError, undefined],
  ["502", () => json({ ok: false, reason: "no-answer" }, 502), ServerError, "no-answer"],
];

for (const [name, answer, ErrorClass, code] of errorCases) {
  test(`an error answer becomes an error: ${name}`, async () => {
    const response = answer();
    const { client, sent } = fake(response);
    const error = await client.scrape("https://example.com").catch((e: unknown) => e);
    assert.ok(error instanceof ErrorClass);
    assert.equal(error.status, response.status);
    assert.equal(error.code, code);
    assert.ok(error.message);
    assert.equal(sent.length, 1); // none of these is retried
  });
}

test("a payment error keeps its message and actions", async () => {
  const { client } = fake(json({ error: "no_credit", message: "Out of credits", actions: { subscribe: "u" } }, 402));
  const error = await client.search("x").catch((e: unknown) => e);
  assert.ok(error instanceof PaymentRequiredError);
  assert.equal(error.message, "Out of credits");
  assert.deepEqual(error.actions, { subscribe: "u" });
});

test("busy is retried, waiting Retry-After", async () => {
  const { client, sent } = fake(json({ ok: false, reason: "busy" }, 503, { "retry-after": "3" }), json(PAGE));
  assert.ok((await client.scrape("https://example.com")).ok);
  assert.equal(sent.length, 2);
  assert.deepEqual(waits, [3000]);
});

test("retries stop after maxRetries", async () => {
  const { client, sent } = fake(...Array.from({ length: 4 }, () => json({ error: "rate_limited" }, 429)));
  await assert.rejects(client.search("x"), RateLimitError);
  assert.equal(sent.length, 4); // the first try and 3 retries
});

test("500 is retried for search but not for starting a job", async () => {
  let { client, sent } = fake(new Response(null, { status: 500 }), json({ results: [] }));
  assert.deepEqual((await client.search("x")).results, []);
  assert.equal(sent.length, 2);

  ({ client, sent } = fake(new Response(null, { status: 500 }), json({ job_id: "j_1" })));
  await assert.rejects(client.startScrapeJob(["https://example.com"]), ServerError);
  assert.equal(sent.length, 1);
});

test("scrapeBatch yields the items and skips the summary", async () => {
  const { client } = fake(
    ndjson(
      { url: "https://a.com", ok: true, result: PAGE, cost: "0.500", effort: 1 },
      { url: "https://b.com", ok: false, error: "upstream status 502" },
      { summary: { cost: "0.500", priced: 1, urls: 2 } },
    ),
  );
  const items = await collect(client.scrapeBatch(["https://a.com", "https://b.com"]));
  assert.deepEqual(items.map((i) => i.url), ["https://a.com", "https://b.com"]);
  assert.equal(items[0]?.result?.markdown, "# Hi");
  assert.equal(items[0]?.cost, 0.5);
  assert.ok(!items[1]?.ok && items[1]?.error === "upstream status 502" && items[1]?.result === undefined);
});

test("a line split across two chunks is read whole", async () => {
  const text = JSON.stringify({ url: "https://a.com", ok: true }) + "\n";
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text.slice(0, 10)));
      controller.enqueue(new TextEncoder().encode(text.slice(10)));
      controller.close();
    },
  });
  const { client } = fake(new Response(stream));
  const items = await collect(client.scrapeBatch(["https://a.com"]));
  assert.deepEqual(items.map((i) => i.url), ["https://a.com"]);
});

test("waitScrapeJob and getScrapeJobResults read every page", async () => {
  const { client, sent } = fake(
    json({ job_id: "j_1", status: "pending" }),
    json({ job_id: "j_1", status: "running", counts: { pending: 1 } }),
    json({ job_id: "j_1", status: "done", counts: { done: 1, error: 1 } }),
    ndjson(
      { url: "https://a.com", ok: true, markdown: "# A", seq: 0 },
      { url: "https://b.com", ok: false, error: { class: "transient_exhausted", detail: "http 502" }, seq: 1 },
    ),
    new Response(""),
  );
  const job = await client.waitScrapeJob("j_1", { pollInterval: 1500 });
  assert.equal(job.status, "done");
  assert.deepEqual(job.counts, { done: 1, error: 1 });
  assert.deepEqual(waits, [1500, 1500]);

  const items = await collect(client.getScrapeJobResults("j_1"));
  assert.deepEqual(items.map((i) => i.url), ["https://a.com", "https://b.com"]);
  assert.equal(items[1]?.error?.class, "transient_exhausted");
  assert.deepEqual(sent.slice(3).map((s) => s.url.searchParams.get("after")), ["0", "2"]);
});

test("waitScrapeJob times out", async () => {
  const now = [0, 5000, 11000];
  mock.method(Date, "now", () => now.shift());
  const { client } = fake(json({ status: "running" }), json({ status: "running" }));
  await assert.rejects(client.waitScrapeJob("j_1", { timeout: 10_000 }), APITimeoutError);
});

test("waitScrapeJob never sleeps past its timeout", async () => {
  const now = [0, 9000, 10000];
  mock.method(Date, "now", () => now.shift());
  const { client } = fake(json({ status: "running" }), json({ status: "running" }));
  await assert.rejects(client.waitScrapeJob("j_1", { pollInterval: 5000, timeout: 10_000 }), APITimeoutError);
  assert.deepEqual(waits, [1000]); // 1 s left, not the full 5 s
});

test("retryScrapeJob reads usage", async () => {
  const { client } = fake(json({ job_id: "j_1", retrying: 2, usage: { units: 2 } }));
  const result = await client.retryScrapeJob("j_1");
  assert.equal(result.retrying, 2);
  assert.deepEqual(result.usage, { units: 2 });
});

test("search sends deep as 1 and reads markdown and deep_pages", async () => {
  const { client, sent } = fake(
    json({
      results: [{ url: "https://a.com", markdown: "# A" }, { url: "https://b.com" }],
      deep: { launched: 2, got: 1, from_archive: 0, late: 1, ms: 900 },
      usage: { deep_pages: 1 },
    }),
  );
  const result = await client.search("x", { deep: true });
  assert.equal(sent[0]!.url.searchParams.get("deep"), "1");
  assert.equal(sent[0]!.url.searchParams.has("rich"), false);
  assert.deepEqual(result.results.map((r) => r.markdown), ["# A", undefined]);
  assert.equal(result.deep?.got, 1);
  assert.equal(result.usage?.deep_pages, 1);
});

test("answer sends the schema as JSON text and deep as 0", async () => {
  const { client, sent } = fake(
    json({ answered: true, answer: { text: '{"city":"Paris"}', source: "crawl4ai", sources: [{ title: "T", url: "u" }] } }),
  );
  const result = await client.answer("capital of France?", { schema: { type: "object" }, deep: false });
  const params = sent[0]!.url.searchParams;
  assert.equal(params.get("schema"), '{"type":"object"}');
  assert.equal(params.get("deep"), "0");
  assert.equal(params.get("q"), "capital of France?");
  assert.deepEqual(JSON.parse(result.answer!.text), { city: "Paris" });
  assert.equal(result.answer?.sources?.[0]?.url, "u");
});

test("serp reads nested results and keeps every block", async () => {
  const { client, sent } = fake(
    json({
      results: [{ position: 1, domain: "example.com", sitelinks: [{ title: "Docs", url: "u" }] }],
      blocks: ["organic"],
      knowledge_panel: { title: "X" },
    }),
  );
  const result = await client.serp("crm", { num: 20, fresh: true });
  assert.equal(sent[0]?.url.searchParams.get("num"), "20");
  assert.equal(sent[0]?.url.searchParams.get("fresh"), "1");
  assert.equal(result.results[0]?.sitelinks?.[0]?.title, "Docs");
  assert.deepEqual(result.knowledge_panel, { title: "X" });
});

test("extract takes a url or your own content", async () => {
  const { client, sent } = fake(json({ ok: true, data: [] }), json({ ok: true, data: [] }));
  await client.extract("https://example.com", { instruction: "the title" });
  await client.extract({ content: "<p>$5</p>", schema: { type: "object" } });
  assert.deepEqual(sent[0]?.json, { url: "https://example.com", instruction: "the title" });
  assert.deepEqual(sent[1]?.json, { content: "<p>$5</p>", schema: { type: "object" } });
});

test("the job id is escaped in the path", async () => {
  const { client, sent } = fake(json({ status: "done" }));
  await client.getScrapeJob("a/b");
  assert.equal(sent[0]?.url.pathname, "/scrape/jobs/a%2Fb");
});

for (const jobId of ["", ".", ".."]) {
  test(`a job id that is a folder step is refused: ${JSON.stringify(jobId)}`, async () => {
    const { client, sent } = fake();
    await assert.rejects(client.getScrapeJob(jobId), TypeError);
    assert.equal(sent.length, 0); // `..` would have sent the call to /scrape
  });
}

/** A fetch that answers only when its request is aborted, like a server that never replies. */
function silentFetch(_url: string | URL | Request, init?: RequestInit): Promise<Response> {
  return new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
  });
}

test("no answer in time throws APITimeoutError and is not retried", async () => {
  let calls = 0;
  const fetch = (url: string | URL | Request, init?: RequestInit) => {
    calls++;
    return silentFetch(url, init);
  };
  const client = new Crawl4AI({ apiKey: "sk_test", timeout: 20, fetch });
  await assert.rejects(client.search("x"), APITimeoutError);
  assert.equal(calls, 1);
});

test("a network failure is retried for search but not for starting a job", async () => {
  let calls = 0;
  const fetch = async () => {
    calls++;
    if (calls === 1) throw new TypeError("fetch failed");
    return json({ results: [] });
  };
  const client = new Crawl4AI({ apiKey: "sk_test", fetch });
  assert.deepEqual((await client.search("x")).results, []);
  assert.equal(calls, 2);

  calls = 0;
  await assert.rejects(client.startScrapeJob(["https://example.com"]), (e) => !(e instanceof APITimeoutError) && e instanceof APIConnectionError);
  assert.equal(calls, 1);
});

test("a stream that stops sending throws APITimeoutError", async () => {
  const fetch = async (_url: string | URL | Request, init?: RequestInit) => {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(JSON.stringify({ url: "https://a.com", ok: true }) + "\n"));
        init?.signal?.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
      },
    });
    return new Response(stream);
  };
  const client = new Crawl4AI({ apiKey: "sk_test", timeout: 20, fetch });
  const items = client.scrapeBatch(["https://a.com", "https://b.com"]);
  assert.equal((await items.next()).value?.url, "https://a.com");
  await assert.rejects(items.next(), APITimeoutError);
});

test("time the caller spends between lines does not count as a timeout", async () => {
  const lines = [{ url: "https://a.com", ok: true }, { url: "https://b.com", ok: true }];
  const client = new Crawl4AI({ apiKey: "sk_test", timeout: 20, fetch: async () => ndjson(...lines) });
  const urls: string[] = [];
  for await (const item of client.scrapeBatch(["https://a.com", "https://b.com"])) {
    urls.push(item.url);
    await new Promise((resolve) => setTimeout(resolve, 40)); // twice the timeout
  }
  assert.deepEqual(urls, ["https://a.com", "https://b.com"]);
});

test("the last line without a newline stops the timer before the caller gets it", async () => {
  let signal: AbortSignal | undefined;
  const fetch = async (_url: string | URL | Request, init?: RequestInit) => {
    signal = init?.signal ?? undefined;
    return new Response(JSON.stringify({ url: "https://a.com", ok: true, content_hash: null }));
  };
  const client = new Crawl4AI({ apiKey: "sk_test", timeout: 20, fetch });
  const items = client.scrapeBatch(["https://a.com"]);
  const item: ScrapeBatchItem | undefined = (await items.next()).value;
  assert.equal(item?.url, "https://a.com");
  await new Promise((resolve) => setTimeout(resolve, 40)); // twice the timeout, the caller still holding the item
  assert.equal(signal?.aborted, false);
  const row: ScrapeJobItem = { url: "https://a.com", ok: false, content_hash: null }; // compiles: the spec allows null
  assert.equal(row.content_hash, null);
});

test("tools.find sends the filters and reads the page", async () => {
  const { client, sent } = fake(json({ tools: [{ id: "amazon-product", cost: "1 cr" }], total: 3, next_cursor: "2" }));
  const page = await client.tools.find("amazon product", { kind: "sites", essential: true, limit: 2 });
  assert.equal(sent[0]!.url.pathname, "/tools");
  assert.equal(sent[0]!.url.search, "?q=amazon+product&kind=sites&essential=true&limit=2");
  assert.equal(page.tools[0]?.id, "amazon-product");
  assert.equal(page.next_cursor, "2");
});

test("tools.get and tools.estimate read the tool", async () => {
  const { client, sent } = fake(
    json({ id: "scrape", inputs: [{ name: "url", required: true }], cost: { text: "0.05 to 2 cr" } }),
    json({ tool: "amazon-product", text: "1 cr" }),
  );
  const tool = await client.tools.get("scrape");
  assert.equal(tool.inputs?.[0]?.name, "url");
  assert.deepEqual(tool.cost, { text: "0.05 to 2 cr" }); // the tool's price, not the call's cost header
  assert.equal((await client.tools.estimate("amazon-product", { product: "B0" })).text, "1 cr");
  assert.equal(sent[1]!.method, "POST");
  assert.equal(sent[1]!.url.pathname, "/tools/amazon-product/estimate");
  assert.deepEqual(sent[1]!.json, { product: "B0" });
});

test("tools.run posts the inputs and fresh and reads rows", async () => {
  const { client, sent } = fake(
    json({ tool: "amazon-product", request_id: "req_1", usage: { credits: 1 }, rows: [{ asin: "B0" }] }, 200, {
      "x-c4-cost": "1.000",
    }),
  );
  const run = await client.tools.run("amazon-product", { product: "B0", fresh: "an input" }, { fresh: true });
  assert.deepEqual(sent[0]!.json, { product: "B0", fresh: "an input" });
  assert.equal(sent[0]!.headers["Crawl4AI-Fresh"], "true");
  assert.deepEqual(run.rows, [{ asin: "B0" }]);
  assert.equal(run.cost, 1);
});

test("tools errors keep details and did_you_mean", async () => {
  const { client } = fake(
    json({ error: "invalid_input", details: [{ problem: "url is required" }] }, 422),
    json({ error: "tool_not_found", did_you_mean: ["amazon-product"] }, 404),
  );
  const invalid = await client.tools.run("scrape", {}).catch((e: unknown) => e);
  assert.ok(invalid instanceof BadRequestError);
  assert.equal(invalid.message, "invalid_input: url is required");
  const missing = await client.tools.get("amazon-produc").catch((e: unknown) => e);
  assert.ok(missing instanceof NotFoundError);
  assert.deepEqual(missing.body?.did_you_mean, ["amazon-product"]);
});

test("tools.run is not sent again after a 500, and tool_failing is not retried", async () => {
  const { client, sent } = fake(json({}, 500), json({ error: "tool_failing" }, 503));
  await assert.rejects(client.tools.run("amazon-product", { product: "B0" }), ServerError);
  await assert.rejects(client.tools.find("amazon"), (e: Crawl4AIError) => e.code === "tool_failing");
  assert.equal(sent.length, 2);
  assert.deepEqual(waits, []);
});

test("a tool id that is a folder step is refused before any call", async () => {
  const { client, sent } = fake();
  await assert.rejects(client.tools.run("..", {}), TypeError);
  assert.equal(sent.length, 0);
});

test("a cost header that is not a number, or missing, never leaks a body field", async () => {
  const { client } = fake(json({ ...PAGE, cost: "7.5" }, 200, { "x-c4-balance": "abc" }));
  const page = await client.scrape("https://example.com");
  assert.equal(page.cost, undefined);
  assert.equal(page.balance, undefined);
});

test("the default fetch is called as a plain function, as a browser needs", async () => {
  const real = globalThis.fetch;
  let self: unknown = "not called";
  globalThis.fetch = function (this: unknown) {
    self = this;
    return Promise.resolve(json(PAGE));
  } as typeof fetch;
  try {
    await new Crawl4AI({ apiKey: "sk_test" }).scrape("https://example.com");
  } finally {
    globalThis.fetch = real;
  }
  assert.equal(self, globalThis); // not the client: a browser's fetch throws "Illegal invocation" then
});

test("without a key only tools.find and tools.get are sent", async () => {
  const seen: (string | undefined)[] = [];
  const fetch = async (_url: string | URL | Request, init?: RequestInit) => {
    seen.push((init?.headers as Record<string, string>).Authorization);
    return json({ tools: [], id: "scrape" });
  };
  const client = new Crawl4AI({ fetch });
  await client.tools.find("amazon");
  await client.tools.get("scrape");
  await assert.rejects(client.tools.run("scrape", {}), AuthenticationError);
  await assert.rejects(client.tools.estimate("scrape", {}), AuthenticationError);
  assert.deepEqual(seen, [undefined, undefined]);
});

test("tools.batch posts the tool and inputs and is not sent again after a 500", async () => {
  const job = { tool: "scrape", request_id: "req_1", data: { job_id: "j_1", status: "pending" } };
  let { client, sent } = fake(json(job, 202));
  const run = await client.tools.batch("scrape", [{ url: "https://example.com" }]);
  assert.equal(sent[0]!.url.pathname, "/tools/batch");
  assert.deepEqual(sent[0]!.json, { tool: "scrape", inputs: [{ url: "https://example.com" }] });
  assert.equal((run.data as { job_id: string }).job_id, "j_1");
  ({ client, sent } = fake(new Response(null, { status: 500 }), json(job, 202)));
  await assert.rejects(client.tools.batch("scrape", [{ url: "https://example.com" }]), ServerError);
  assert.equal(sent.length, 1);
});
