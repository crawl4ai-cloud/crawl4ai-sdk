// Live tests against the real API. They run only when CRAWL4AI_API_KEY is set, and they spend a few
// credits. CRAWL4AI_BASE_URL points them at another address.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { Crawl4AI } from "../dist/index.js";

const key = process.env.CRAWL4AI_API_KEY;

describe("live", { skip: !key && "CRAWL4AI_API_KEY is not set" }, () => {
  const client = () => new Crawl4AI({ apiKey: key, baseUrl: process.env.CRAWL4AI_BASE_URL });

  test("scrape", async () => {
    const page = await client().scrape("https://example.com", { format: "md" });
    assert.ok(page.ok && page.markdown);
  });

  test("scrapeBatch", async () => {
    const items = [];
    for await (const item of client().scrapeBatch(["https://example.com"], { format: "md" })) items.push(item);
    assert.equal(items.length, 1);
    assert.ok(items[0]?.ok && items[0].result?.markdown);
  });

  test("scrape job", async () => {
    const c = client();
    const job = await c.startScrapeJob(["https://example.com"], { format: "md" });
    assert.ok(job.job_id);
    assert.equal((await c.waitScrapeJob(job.job_id, { pollInterval: 1000, timeout: 300_000 })).status, "done");
    const items = [];
    for await (const item of c.getScrapeJobResults(job.job_id)) items.push(item);
    assert.deepEqual(items.map((i) => i.url), ["https://example.com"]);
    assert.ok(items[0]?.ok);
  });

  test("search", async () => {
    assert.ok((await client().search("example domain")).results.length);
  });

  test("serp", async () => {
    assert.ok(Array.isArray((await client().serp("example domain")).results));
  });

  test("answer with a schema", async () => {
    const schema = { type: "object", properties: { city: { type: "string" } } };
    const result = await client().answer("What is the capital of France?", { schema });
    assert.equal(typeof result.answered, "boolean");
  });

  test("extract", async () => {
    const result = await client().extract({ content: "<h1>Hello</h1><p>Price: $5</p>", instruction: "the price" });
    assert.ok(result.ok);
  });
});
