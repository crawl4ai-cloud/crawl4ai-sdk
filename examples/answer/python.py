"""Ask a question and get a direct answer with its sources (experimental)."""

import json

from crawl4ai_cloud import Crawl4AI

with Crawl4AI() as client:
    result = client.answer("Who created the Python language?")
    if result.answered:
        print(result.answer.text)
        for source in result.answer.sources or []:
            print("  source:", source.url)

    # With a schema, the answer is JSON text in that shape.
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "year": {"type": "integer"}},
    }
    result = client.answer("Who created Python, and in what year?", schema=schema)
    if result.answered:
        print(json.loads(result.answer.text))
