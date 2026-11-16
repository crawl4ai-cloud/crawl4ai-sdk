"""Scrape up to 50 pages at once. Each page prints as soon as it is ready."""

from crawl4ai_cloud import Crawl4AI

urls = [
    "https://example.com",
    "https://example.org",
    "https://www.iana.org/help/example-domains",
]

with Crawl4AI() as client:
    for item in client.scrape_batch(urls, format="md"):
        if item.ok:
            print(item.url, "->", len(item.result.markdown or ""), "chars")
        else:
            print(item.url, "failed:", item.error)
