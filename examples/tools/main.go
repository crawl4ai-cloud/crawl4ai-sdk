// The Toolkit: find a tool, read its inputs, price a run, run it.
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

	list, err := client.Tools.Find(ctx, "amazon", nil)
	if err != nil {
		log.Fatal(err)
	}
	for _, tool := range list.Tools {
		fmt.Println(tool.ID, "-", tool.Cost, "-", tool.Summary)
	}

	tool, err := client.Tools.Get(ctx, "amazon-product")
	if err != nil {
		log.Fatal(err)
	}
	for _, input := range tool.Inputs {
		fmt.Println("input:", input.Name)
	}

	inputs := map[string]any{"product": "B0F5HSNDXF"}
	est, err := client.Tools.Estimate(ctx, "amazon-product", inputs)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("price:", est.Data["text"])

	run, err := client.Tools.Run(ctx, "amazon-product", inputs, nil)
	if err != nil {
		log.Fatal(err)
	}
	for _, row := range run.Rows {
		fmt.Println(row["title"], row["price"])
	}
}
