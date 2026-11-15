// Scrape up to 10,000 pages in the background: start a job, wait, read the results, retry failures.
package main

import (
	"context"
	"fmt"
	"log"
	"time"

	crawl4ai "github.com/crawl4ai-cloud/crawl4ai-sdk/go"
)

func main() {
	ctx := context.Background()
	urls := []string{"https://example.com", "https://example.org"}

	client, err := crawl4ai.NewClient()
	if err != nil {
		log.Fatal(err)
	}
	job, err := client.StartScrapeJob(ctx, urls, &crawl4ai.ScrapeOptions{Format: "md"})
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("started", job.JobID)

	job, err = client.WaitScrapeJob(ctx, job.JobID, &crawl4ai.WaitOptions{Timeout: 10 * time.Minute})
	if err != nil {
		log.Fatal(err)
	}
	fmt.Printf("status: %s counts: %+v\n", job.Status, job.Counts)

	for item, err := range client.GetScrapeJobResults(ctx, job.JobID) {
		if err != nil {
			log.Fatal(err)
		}
		if item.OK {
			fmt.Println(item.URL, "ok")
		} else {
			fmt.Printf("%s failed: %+v\n", item.URL, item.Error)
		}
	}

	if job.Counts.Error > 0 {
		retry, err := client.RetryScrapeJob(ctx, job.JobID)
		if err != nil {
			log.Fatal(err)
		}
		fmt.Println("retrying", retry.Retrying, "URLs")
	}
}
