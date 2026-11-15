// Handle the errors a call can return.
package main

import (
	"context"
	"errors"
	"fmt"
	"log"

	crawl4ai "github.com/crawl4ai-cloud/crawl4ai-sdk/go"
)

func main() {
	var page *crawl4ai.ScrapeResult
	client, err := crawl4ai.NewClient() // a missing key is an ErrAuthentication too
	if err == nil {
		page, err = client.Scrape(context.Background(), "https://example.com", nil)
	}
	var e *crawl4ai.Error
	switch {
	case err == nil:
		fmt.Println(page.Markdown)
	case errors.Is(err, crawl4ai.ErrAuthentication):
		fmt.Println("the key is missing or not valid")
	case errors.Is(err, crawl4ai.ErrPaymentRequired) && errors.As(err, &e):
		fmt.Println(e.Message, e.Actions["subscribe"])
	case errors.Is(err, crawl4ai.ErrBlocked) && errors.As(err, &e):
		fmt.Println("the site refused:", e.Code)
	case errors.Is(err, crawl4ai.ErrRateLimit):
		fmt.Println("too many calls; slow down")
	case errors.As(err, &e):
		fmt.Printf("failed (%d, %s): %s\n", e.Status, e.Code, e.Message)
	default:
		log.Fatal(err)
	}
}
