// Handle the errors a call can throw.
import {
  AuthenticationError,
  BlockedError,
  Crawl4AI,
  Crawl4AIError,
  PaymentRequiredError,
  RateLimitError,
} from "crawl4ai-cloud";

try {
  const page = await new Crawl4AI().scrape("https://example.com");
  console.log(page.markdown);
} catch (e) {
  if (e instanceof AuthenticationError) console.log("the key is missing or not valid");
  else if (e instanceof PaymentRequiredError) console.log(e.message, e.actions?.subscribe);
  else if (e instanceof BlockedError) console.log("the site refused:", e.code);
  else if (e instanceof RateLimitError) console.log("too many calls; slow down");
  else if (e instanceof Crawl4AIError) console.log(`failed (${e.status}, ${e.code}): ${e.message}`);
  else throw e;
}
