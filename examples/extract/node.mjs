// Pull structured JSON out of a page, or out of your own text.
import { Crawl4AI } from "crawl4ai-cloud";

const client = new Crawl4AI();
let result = await client.extract("https://news.ycombinator.com", { instruction: "the top 3 story titles" });
console.log(result.data);

const schema = { type: "object", properties: { product: { type: "string" }, price: { type: "number" } } };
result = await client.extract({ content: "<h1>Blue Mug</h1><p>Price: $12.50</p>", schema });
console.log(result.data);
