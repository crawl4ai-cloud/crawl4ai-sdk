"""The Toolkit: find a tool, read its inputs, price a run, run it."""

from crawl4ai_cloud import Crawl4AI

with Crawl4AI() as client:
    for tool in client.tools.find("amazon").tools or []:
        print(tool.id, "-", tool.cost, "-", tool.summary)

    tool = client.tools.get("amazon-product")
    print("inputs:", [i["name"] for i in tool.inputs or []])
    print("price:", client.tools.estimate("amazon-product", {"product": "B0F5HSNDXF"}).data["text"])

    run = client.tools.run("amazon-product", {"product": "B0F5HSNDXF"})
    for row in run.rows or []:
        print(row.get("title"), row.get("price"))
