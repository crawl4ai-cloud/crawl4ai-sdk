// Scrape up to 50 pages at once. Each page prints as soon as it is ready.
package main

import (
	"context"
	"fmt"
	"log"

	crawl4ai "github.com/crawl4ai-cloud/crawl4ai-sdk/go"
)

func main() {
	urls := []string{"https://example.com", "https://example.org", "https://www.iana.org/help/example-domains"}

	client, err := crawl4ai.NewClient()
	if err != nil {
		log.Fatal(err)
	}
	for item, err := range client.ScrapeBatch(context.Background(), urls, &crawl4ai.ScrapeOptions{Format: "md"}) {
		if err != nil {
			log.Fatal(err)
		}
		if item.OK {
			fmt.Println(item.URL, "->", len(item.Result.Markdown), "chars")
		} else {
			fmt.Println(item.URL, "failed:", item.Error)
		}
	}
}
