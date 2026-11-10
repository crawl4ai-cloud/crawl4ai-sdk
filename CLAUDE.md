# Crawl4AI Cloud SDKs: instructions for coding agents

This is a PUBLIC repository. Everything you write here can be read by anyone.

- **Never write a secret.** No API key, token or `.env` file. Tests use a mock server or
  `CRAWL4AI_API_KEY` from the environment, and skip a live test when it is unset.
- **Only the public API.** The base URL is `https://api.crawl4ai.com`. Never write an internal
  address (10.x, 172.x, 192.168.x), a server or box name, a region's internal detail, or how the
  service works inside. If you learned it from the private fleet repository, it does not belong here.
- **`spec/openapi.yaml` is the contract.** Change the spec first, then every SDK that is affected.
- **Same names in every language.** A method, parameter or field has one name across the SDKs,
  written in each language's own style (`scrape_page` in Python, `scrapePage` in Node).
- **Docs for agents.** Every public method has a doc comment with one runnable example.
- Branch, pull request to `main`. Only the maintainer merges.
