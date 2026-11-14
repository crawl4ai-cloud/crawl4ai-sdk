"""Search the web, and get Google's results page as data."""

from crawl4ai_cloud import Crawl4AI

with Crawl4AI() as client:
    for result in client.search("rust web crawler").results or []:
        print(result.title, "-", result.url)

    serp = client.serp("best crm software", country="us", num=10)
    for result in serp.results or []:
        print(result.position, result.domain, result.title)
