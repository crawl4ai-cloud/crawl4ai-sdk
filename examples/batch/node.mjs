// Scrape up to 50 pages at once. Each page prints as soon as it is ready.
import { Crawl4AI } from "crawl4ai-cloud";

const urls = ["https://example.com", "https://example.org", "https://www.iana.org/help/example-domains"];

const client = new Crawl4AI();
for await (const item of client.scrapeBatch(urls, { format: "md" })) {
  if (item.ok) console.log(item.url, "->", item.result?.markdown?.length ?? 0, "chars");
  else console.log(item.url, "failed:", item.error);
}
