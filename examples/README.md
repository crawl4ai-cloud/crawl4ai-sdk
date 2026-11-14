# Examples

One folder per task (scrape a page, extract JSON, search, batch), each with the same task in every language.

| Folder | What it shows |
|---|---|
| `scrape` | One page to Markdown |
| `batch` | Up to 50 pages, each printed as soon as it is ready |
| `job` | Up to 10,000 pages in the background: start, wait, read results, retry failures |
| `search` | Web search, and Google's results page as data |
| `answer` | A direct answer with sources, plain or in a JSON Schema's shape |
| `extract` | Structured JSON from a page or from your own text |
| `errors` | Catching each kind of error |

Run one with your key in the environment. Each run spends a few credits.

```bash
pip install crawl4ai-cloud-sdk
export CRAWL4AI_API_KEY=sk_live_...
python examples/scrape/python.py
```
