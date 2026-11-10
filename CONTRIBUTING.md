# Contributing

Thank you for helping. A few rules keep this repository safe and easy to review.

## The rules

1. **No secrets, ever.** No API keys, tokens, passwords or `.env` files. Tests use a mock server or
   read `CRAWL4AI_API_KEY` from the environment. GitHub push protection blocks known key formats.
2. **Public API only.** The SDKs talk to `https://api.crawl4ai.com` and nothing else. No internal
   addresses, server names or service details in code, tests, docs or comments.
3. **The spec first.** A new endpoint or field goes into `spec/openapi.yaml` first, then into each SDK.
4. **Small pull requests.** One purpose per pull request, with tests. The maintainer reviews and merges.
5. **Plain English.** Short sentences, common words, in code comments and docs.

## How

Fork, branch, change, run the tests of the folder you touched, open a pull request against `main`.
Each folder's README says how to build and test it.
