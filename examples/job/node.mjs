// Scrape up to 10,000 pages in the background: start a job, wait, read the results, retry failures.
import { Crawl4AI } from "crawl4ai-cloud";

const urls = ["https://example.com", "https://example.org"];

const client = new Crawl4AI();
let job = await client.startScrapeJob(urls, { format: "md" });
console.log("started", job.job_id);

job = await client.waitScrapeJob(job.job_id, { timeout: 600_000 });
console.log("status:", job.status, "counts:", job.counts);

for await (const item of client.getScrapeJobResults(job.job_id)) {
  console.log(item.url, item.ok ? "ok" : `failed: ${JSON.stringify(item.error)}`);
}

if (job.counts?.error) {
  console.log("retrying", (await client.retryScrapeJob(job.job_id)).retrying, "URLs");
}
