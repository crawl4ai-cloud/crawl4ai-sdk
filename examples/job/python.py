"""Scrape up to 10,000 pages in the background: start a job, wait, read the results, retry failures."""

from crawl4ai_cloud import Crawl4AI

urls = ["https://example.com", "https://example.org"]

with Crawl4AI() as client:
    job = client.start_scrape_job(urls, format="md")
    print("started", job.job_id)

    job = client.wait_scrape_job(job.job_id, timeout=600)
    print("status:", job.status, "counts:", job.counts)

    for item in client.get_scrape_job_results(job.job_id):
        print(item.url, "ok" if item.ok else f"failed: {item.error}")

    if job.counts and job.counts.get("error"):
        print("retrying", client.retry_scrape_job(job.job_id).retrying, "URLs")
