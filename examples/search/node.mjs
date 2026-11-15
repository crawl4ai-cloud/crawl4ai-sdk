// Search the web, and get Google's results page as data.
import { Crawl4AI } from "crawl4ai-cloud";

const client = new Crawl4AI();
for (const result of (await client.search("rust web crawler")).results) {
  console.log(result.title, "-", result.url);
}

const serp = await client.serp("best crm software", { country: "us", num: 10 });
for (const result of serp.results) console.log(result.position, result.domain, result.title);
