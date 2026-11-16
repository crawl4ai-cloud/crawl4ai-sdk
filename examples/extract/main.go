// Pull structured JSON out of a page, or out of your own text.
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
	res, err := client.Extract(ctx, &crawl4ai.ExtractOptions{URL: "https://news.ycombinator.com", Instruction: "the top 3 story titles"})
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(string(res.Data))

	schema := map[string]any{"type": "object", "properties": map[string]any{
		"product": map[string]any{"type": "string"},
		"price":   map[string]any{"type": "number"},
	}}
	res, err = client.Extract(ctx, &crawl4ai.ExtractOptions{Content: "<h1>Blue Mug</h1><p>Price: $12.50</p>", Schema: schema})
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(string(res.Data))
}
