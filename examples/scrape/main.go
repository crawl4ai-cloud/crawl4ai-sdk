// Scrape one page to Markdown. Run: CRAWL4AI_API_KEY=sk_live_... go run ./scrape
package main

import (
	"context"
	"fmt"
	"log"

	crawl4ai "github.com/crawl4ai-cloud/crawl4ai-sdk/go"
)

func main() {
	client, err := crawl4ai.NewClient()
	if err != nil {
		log.Fatal(err)
	}
	page, err := client.Scrape(context.Background(), "https://example.com", &crawl4ai.ScrapeOptions{Format: "md"})
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(page.Markdown)
	if page.Cost != nil {
		fmt.Printf("engine: %s, took %d ms, cost %g credits\n", page.Engine, page.Ms, *page.Cost)
	} else {
		fmt.Printf("engine: %s, took %d ms\n", page.Engine, page.Ms)
	}
}
