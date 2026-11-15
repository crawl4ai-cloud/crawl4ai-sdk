// Search the web, and get Google's results page as data.
package main

import (
	"context"
	"fmt"
	"log"

	crawl4ai "github.com/crawl4ai-cloud/crawl4ai-sdk/go"
)

func main() {
	ctx := context.Background()
	client, err := crawl4ai.NewClient()
	if err != nil {
		log.Fatal(err)
	}
	res, err := client.Search(ctx, "rust web crawler", nil)
	if err != nil {
		log.Fatal(err)
	}
	for _, r := range res.Results {
		fmt.Println(r.Title, "-", r.URL)
	}

	serp, err := client.Serp(ctx, "best crm software", &crawl4ai.SerpOptions{Country: "us", Num: 10})
	if err != nil {
		log.Fatal(err)
	}
	for _, r := range serp.Results {
		fmt.Println(r.Position, r.Domain, r.Title)
	}
}
