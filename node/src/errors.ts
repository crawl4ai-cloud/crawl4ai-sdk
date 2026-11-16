/** The errors the SDK throws. Catch `Crawl4AIError` to catch them all. */

/**
 * Every error the SDK throws.
 *
 * `status` is the HTTP status (undefined when no answer came back), `code` the server's short code
 * (`no_credit`, `blocked`, ...), `message` text you can show to people as it is, and `actions`
 * the server's links that fix the problem (for example `subscribe`).
 */
export class Crawl4AIError extends Error {
  readonly status?: number;
  readonly code?: string;
  readonly actions?: Record<string, unknown>;

  constructor(
    message: string,
    options: { status?: number; code?: string; actions?: Record<string, unknown>; cause?: unknown } = {},
  ) {
    super(message, { cause: options.cause });
    this.name = new.target.name;
    this.status = options.status;
    this.code = options.code;
    this.actions = options.actions;
  }
}

/** 400 or 422: a field is wrong. `message` says which. */
export class BadRequestError extends Crawl4AIError {}

/** 401: the API key is missing or not valid. */
export class AuthenticationError extends Crawl4AIError {}

/** 402: out of credit. `code` is `no_credit`, `plan_cap`, `spend_cap` or `plan_needed`. */
export class PaymentRequiredError extends Crawl4AIError {}

/** 403 from `/scrape`: the site refused every attempt. `code` is `blocked` or `login-wall`. */
export class BlockedError extends Crawl4AIError {}

/** 404: no such job, or `not_available` (not open to this account). */
export class NotFoundError extends Crawl4AIError {}

/** 429: over the plan's requests a minute or calls at a time, after every retry. */
export class RateLimitError extends Crawl4AIError {}

/** 5xx: the service or the site failed. `code` says why, for example `busy` or `no-answer`. */
export class ServerError extends Crawl4AIError {}

/** No answer came back: the network failed before the server replied. */
export class APIConnectionError extends Crawl4AIError {}

/** No answer within the timeout, or a job not done before `waitScrapeJob`'s timeout. */
export class APITimeoutError extends APIConnectionError {}
