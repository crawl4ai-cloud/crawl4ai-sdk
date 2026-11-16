"""Live tests against the real API. They run only when CRAWL4AI_API_KEY is set, and they spend a
few credits. CRAWL4AI_BASE_URL points them at another address."""

import os

import pytest

from crawl4ai_cloud import Crawl4AI

pytestmark = pytest.mark.skipif(not os.environ.get("CRAWL4AI_API_KEY"), reason="CRAWL4AI_API_KEY is not set")


@pytest.fixture(scope="module")
def client():
    with Crawl4AI(base_url=os.environ.get("CRAWL4AI_BASE_URL", "https://api.crawl4ai.com")) as c:
        yield c


def test_scrape(client):
    page = client.scrape("https://example.com", format="md")
    assert page.ok and page.markdown


def test_scrape_batch(client):
    items = list(client.scrape_batch(["https://example.com"], format="md"))
    assert len(items) == 1 and items[0].ok and items[0].result.markdown


def test_scrape_job(client):
    job = client.start_scrape_job(["https://example.com"], format="md")
    assert job.job_id
    assert client.wait_scrape_job(job.job_id, poll_interval=1, timeout=300).status == "done"
    items = list(client.get_scrape_job_results(job.job_id))
    assert [i.url for i in items] == ["https://example.com"] and items[0].ok


def test_search(client):
    assert client.search("example domain").results


def test_serp(client):
    assert client.serp("example domain").results is not None


def test_answer_with_schema(client):
    result = client.answer("What is the capital of France?", schema={"type": "object", "properties": {"city": {"type": "string"}}})
    assert result.answered is not None


def test_extract(client):
    result = client.extract(content="<h1>Hello</h1><p>Price: $5</p>", instruction="the price")
    assert result.ok
