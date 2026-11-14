"""Scrape one page to Markdown. Run: CRAWL4AI_API_KEY=sk_live_... python python.py"""

from crawl4ai_cloud import Crawl4AI

with Crawl4AI() as client:
    page = client.scrape("https://example.com", format="md")
    print(page.markdown)
    print(f"engine: {page.engine}, took {page.ms} ms, cost {page.cost} credits")
