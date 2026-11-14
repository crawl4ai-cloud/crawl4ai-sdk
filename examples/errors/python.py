"""Handle the errors a call can raise."""

from crawl4ai_cloud import (
    AuthenticationError,
    BlockedError,
    Crawl4AI,
    Crawl4AIError,
    PaymentRequiredError,
    RateLimitError,
)

with Crawl4AI() as client:
    try:
        page = client.scrape("https://example.com")
        print(page.markdown)
    except AuthenticationError:
        print("the key is missing or not valid")
    except PaymentRequiredError as e:
        print(e.message, (e.actions or {}).get("subscribe"))
    except BlockedError as e:
        print("the site refused:", e.code)
    except RateLimitError:
        print("too many calls; slow down")
    except Crawl4AIError as e:
        print(f"failed ({e.status}, {e.code}): {e.message}")
