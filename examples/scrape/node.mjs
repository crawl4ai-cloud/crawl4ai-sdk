// Scrape one page to Markdown. Run: CRAWL4AI_API_KEY=sk_live_... node node.mjs
import { Crawl4AI } from "crawl4ai-cloud";

const client = new Crawl4AI();
const page = await client.scrape("https://example.com", { format: "md" });
console.log(page.markdown);
console.log(`engine: ${page.engine}, took ${page.ms} ms, cost ${page.cost} credits`);
