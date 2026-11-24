// The Toolkit: find a tool, read its inputs, price a run, run it.
import { Crawl4AI } from "crawl4ai-cloud";

const client = new Crawl4AI();
for (const tool of (await client.tools.find("amazon")).tools) console.log(tool.id, "-", tool.cost, "-", tool.summary);

const tool = await client.tools.get("amazon-product");
console.log("inputs:", tool.inputs?.map((input) => input.name));
console.log("price:", (await client.tools.estimate("amazon-product", { product: "B0F5HSNDXF" })).data?.text);

const run = await client.tools.run("amazon-product", { product: "B0F5HSNDXF" });
for (const row of run.rows ?? []) console.log(row.title, row.price);
