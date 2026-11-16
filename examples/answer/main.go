// Ask a question and get a direct answer with its sources (experimental).
package main

import (
	"context"
	"encoding/json"
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
	res, err := client.Answer(ctx, "Who created the Python language?", nil)
	if err != nil {
		log.Fatal(err)
	}
	if res.Answered {
		fmt.Println(res.Answer.Text)
		for _, source := range res.Answer.Sources {
			fmt.Println("  source:", source.URL)
		}
	}

	// With a schema, the answer is JSON text in that shape.
	schema := map[string]any{"type": "object", "properties": map[string]any{
		"name": map[string]any{"type": "string"},
		"year": map[string]any{"type": "integer"},
	}}
	res, err = client.Answer(ctx, "Who created Python, and in what year?", &crawl4ai.AnswerOptions{Schema: schema})
	if err != nil {
		log.Fatal(err)
	}
	if res.Answered {
		var who struct {
			Name string `json:"name"`
			Year int    `json:"year"`
		}
		if err := json.Unmarshal([]byte(res.Answer.Text), &who); err != nil {
			log.Fatal(err)
		}
		fmt.Printf("%+v\n", who)
	}
}
