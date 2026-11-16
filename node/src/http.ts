/**
 * What every call shares: the key, the headers, when to retry, and how an error answer becomes an
 * error. The client in `client.ts` sends every call through these rules.
 */

import {
  AuthenticationError,
  BadRequestError,
  BlockedError,
  Crawl4AIError,
  NotFoundError,
  PaymentRequiredError,
  RateLimitError,
  ServerError,
} from "./errors.js";
import { VERSION } from "./version.js";

export const BASE_URL = "https://api.crawl4ai.com";
export const TIMEOUT = 120_000; // ms; the docs' advice: a page that needs a real browser can take 90 s
export const MAX_RETRIES = 3;

// CRAWL4AI_KEY is the name llms.txt gives agents; CRAWL4AI_API_KEY is the SDKs' name and wins.
const KEY_ENV_VARS = ["CRAWL4AI_API_KEY", "CRAWL4AI_KEY"];

const ERROR_BY_STATUS: Record<number, typeof Crawl4AIError> = {
  400: BadRequestError,
  401: AuthenticationError,
  402: PaymentRequiredError,
  403: BlockedError,
  404: NotFoundError,
  422: BadRequestError,
  429: RateLimitError,
};

/**
 * Returns the headers of every request. The key is `apiKey`, else the first env var of
 * `KEY_ENV_VARS` that is set; with neither it throws AuthenticationError. A key with a character a
 * header cannot carry throws too, without the key: fetch's own error would quote it whole.
 */
export function headers(apiKey?: string): Record<string, string> {
  const env = globalThis.process?.env ?? {};
  const key = (apiKey || KEY_ENV_VARS.map((name) => env[name]).find(Boolean))?.trim();
  if (!key) throw new AuthenticationError("No API key: pass { apiKey } or set CRAWL4AI_API_KEY.");
  if (!/^[\x21-\x7e]+$/.test(key)) throw new AuthenticationError("The API key has a character that is not allowed.");
  return { Authorization: `Bearer ${key}`, "User-Agent": `crawl4ai-cloud-node/${VERSION}` };
}

/**
 * True when a request that got `status` is worth sending again.
 * 429 and 503 mean the server did not start the work, so every request retries them.
 * 500 and 504 retry only when `safe` (sending the request twice cannot run the work twice).
 */
export function shouldRetry(status: number, safe: boolean): boolean {
  return status === 429 || status === 503 || (safe && (status === 500 || status === 504));
}

/**
 * Milliseconds to wait before retry number `attempt` (0 = the first retry): the server's
 * `Retry-After` when it sends one (at most 60 s), else 0.5 s doubled each time, at most 8 s,
 * with random jitter so many clients do not retry at the same moment.
 */
export function retryDelay(attempt: number, retryAfter?: string | null): number {
  if (retryAfter && /^\d+$/.test(retryAfter)) return Math.min(Number(retryAfter), 60) * 1000;
  return Math.min(500 * 2 ** attempt, 8000) * (0.5 + Math.random() / 2);
}

/** Waits `ms` milliseconds. Tests replace it so retries do not wait. */
export const clock = {
  sleep: (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)),
};

/**
 * Builds the error for an error answer from its status and body text.
 *
 * The server sends `{"error": code, "message": ..., "actions": ...}`, `/scrape` sends
 * `{"ok": false, "reason": code}`, and some errors send plain text or nothing.
 */
export function errorFrom(status: number, text: string): Crawl4AIError {
  let body: Record<string, unknown> = {};
  try {
    const parsed: unknown = JSON.parse(text);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) body = parsed as Record<string, unknown>;
  } catch {
    // plain text or empty: the message falls back to the text
  }
  const rawCode = body.error ?? body.reason;
  const code = rawCode == null ? undefined : String(rawCode);
  const message =
    (typeof body.message === "string" && body.message) || code || text.trim().slice(0, 500) || `HTTP ${status}`;
  const ErrorClass = ERROR_BY_STATUS[status] ?? (status >= 500 ? ServerError : Crawl4AIError);
  const actions = body.actions as Record<string, unknown> | undefined;
  return new ErrorClass(message, { status, code, actions });
}

/** Returns the fields that are not undefined: the request leaves out what the caller did not set. */
export function body(fields: object): Record<string, unknown> {
  return Object.fromEntries(Object.entries(fields).filter(([, value]) => value !== undefined));
}

/** Turns query fields into a query string: booleans become the 0 or 1 the API takes. */
export function query(fields: object): string {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(body(fields))) {
    params.set(name, typeof value === "boolean" ? String(Number(value)) : String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

/**
 * Returns `/scrape/jobs/<jobId><tail>`, with the id escaped for a URL.
 * Throws for an empty id or `.` / `..`, which a URL reads as a folder step.
 */
export function jobPath(jobId: string, tail = ""): string {
  if (jobId === "" || jobId === "." || jobId === "..") throw new TypeError(`Not a job id: ${JSON.stringify(jobId)}`);
  return `/scrape/jobs/${encodeURIComponent(jobId)}${tail}`;
}

/** Reads the cost headers into numbers; a header the server did not send is left out. */
export function costs(response: Response): { cost?: number; balance?: number; allowance_left?: number } {
  const read = (name: string) => {
    const value = response.headers.get(name);
    return value == null ? undefined : Number(value);
  };
  return body({
    cost: read("x-c4-cost"),
    balance: read("x-c4-balance"),
    allowance_left: read("x-c4-allowance-left"),
  });
}
