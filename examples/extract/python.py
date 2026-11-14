"""Pull structured JSON out of a page, or out of your own text."""

from crawl4ai_cloud import Crawl4AI

with Crawl4AI() as client:
    result = client.extract(
        "https://news.ycombinator.com", instruction="the top 3 story titles"
    )
    print(result.data)

    schema = {
        "type": "object",
        "properties": {"product": {"type": "string"}, "price": {"type": "number"}},
    }
    result = client.extract(
        content="<h1>Blue Mug</h1><p>Price: $12.50</p>", schema=schema
    )
    print(result.data)
