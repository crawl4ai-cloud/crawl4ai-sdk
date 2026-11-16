# Directions for every reviewer (read first, follow exactly)

You review one part of the Crawl4AI Cloud SDKs: the official client libraries (Python, Node, Go, Rust)
for a public web-crawling API at https://api.crawl4ai.com. The repository is PUBLIC. `spec/openapi.yaml`
is the contract every SDK follows. The part you review is described at the end of this task.

## What we want from you
Only findings that matter before a release:
1. **Bugs**: wrong output, a crash, a hang, a request the API will reject, a field sent with the wrong
   name or type, a response field parsed wrong or dropped, an error mapped to the wrong class.
2. **Security**: anything that can hurt a user of the SDK or leak their key. Think about: the API key in
   a log, an exception message, a repr or a URL; user input that changes the request path or host; a
   secret, internal address or private detail committed to this public repository; an unsafe default.
3. **Silent mistakes**: code that runs but does the wrong thing quietly (a request retried that must not
   run twice, a timeout that never fires, a page of results skipped, a default that differs from the
   spec, a value that silently becomes None).
4. **Gaps with the spec**: the SDK and `spec/openapi.yaml` disagree on a path, a parameter, a field or a
   status code. Say which one looks right.
5. **Strong improvements**: something we would regret shipping without. Rare. Say why it is not "later".

## What we do NOT want
- Nothing that needs a one-in-a-billion event. If it needs a chain of three unlikely things, drop it.
- No style, naming, formatting, "consider adding a test", "add docs", "could be refactored".
- No over-engineering: no new abstractions, no frameworks, no "make it configurable".
- Do not overthink. Read the code, find real problems, write them down. If you are not sure a
  finding is real, say your confidence honestly (high / medium / low); do not invent certainty.
- Do not propose solutions in detail. One line of "what the fix would be" is enough.
- Do not repeat one root cause as five findings.

## How to work
- The repository is at the current directory. You have read-only access. Read the real code; do not
  guess from names. Quote the exact file and line for every finding.
- Read `spec/openapi.yaml` for the paths your part touches; it says what the API does. The README of
  the SDK says what the SDK promises its users. A gap between either and the code is a finding.
- A behaviour the tests do not cover is not by itself a finding.

## Output format (exactly this, nothing else after it)
Write a Markdown list. One block per finding, ordered by severity (critical, high, medium). Stop at
medium: do not list low items. Maximum 15 findings; fewer is better.

```
### N. <title in one line>
- severity: critical | high | medium
- class: bug | security | silent-mistake | spec-gap | improvement
- where: <path>:<line> (more than one allowed)
- what: <2-4 sentences: what happens, when, and the effect on a user of the SDK>
- how to check: <one concrete way to confirm it: a call, an input, a test>
- fix in one line: <what to change>
- confidence: high | medium | low
```
End with one line: `total: N findings (critical A, high B, medium C)`.
If you find nothing that meets the bar, write `total: 0 findings` and one sentence why.
