// Ask a question and get a direct answer with its sources (experimental).
import { Crawl4AI } from "crawl4ai-cloud";

const client = new Crawl4AI();
let result = await client.answer("Who created the Python language?");
if (result.answered) {
  console.log(result.answer.text);
  for (const source of result.answer.sources ?? []) console.log("  source:", source.url);
}

// With a schema, the answer is JSON text in that shape.
const schema = { type: "object", properties: { name: { type: "string" }, year: { type: "integer" } } };
result = await client.answer("Who created Python, and in what year?", { schema });
if (result.answered) console.log(JSON.parse(result.answer.text));
