/**
 * The one place that talks to the API.
 *
 * Same-origin `/api/...` paths throughout: Vite proxies them to uvicorn in
 * development, and the built SPA is served by uvicorn itself. No base URL,
 * no environment variable, no CORS.
 */
import type { LogLine } from "@/api/types";

export type QueryParams = Record<string, string | number | boolean | undefined>;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

function withParams(path: string, params?: QueryParams): string {
  if (!params) return path;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    // Undefined is "this filter is off", not "filter on the string
    // 'undefined'" — which is what URLSearchParams would otherwise send,
    // and which the server would answer with an empty list.
    if (value !== undefined) search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

async function detailOf(response: Response): Promise<string> {
  // FastAPI's errors are `{"detail": "..."}`. uvicorn's own 502/503 pages
  // are HTML, so a client that assumed JSON would throw a SyntaxError and
  // the screen would report a parse failure rather than the server being
  // down.
  try {
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string"
    ) {
      return body.detail;
    }
  } catch {
    /* fall through to the generic message */
  }
  return `Request failed (${response.status})`;
}

export async function apiGet<T>(path: string, params?: QueryParams): Promise<T> {
  const response = await fetch(withParams(path, params), {
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(response.status, await detailOf(response));
  }
  // The one type assertion in the app, and the reason nothing else needs
  // one: `Response.json()` is `Promise<any>`, so untyped JSON becomes a
  // typed contract exactly here. Callers name `T` from `@/api/types`, and
  // `eslint.config.js` scopes the assertion exemption to this file so that
  // "the app has one cast" stays a fact you can check.
  return (await response.json()) as T;
}

/**
 * A render's PNG.
 *
 * Returned as a URL rather than fetched, because it is an `<img src>`: the
 * browser's own cache and decoding are better at images than anything this
 * layer could add.
 */
export function imageUrl(renderId: string, size: "full" | "thumb"): string {
  return `/api/renders/${encodeURIComponent(renderId)}/image?size=${size}`;
}

export async function apiSend<T>(
  method: "POST" | "PUT",
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      accept: "application/json",
      ...(body === undefined ? {} : { "content-type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await detailOf(response));
  }
  return (await response.json()) as T;
}

/**
 * What `openRunEvents` hands back.
 *
 * `EventTarget & { close() }` rather than `EventSource` because that is the
 * whole of what this app uses, and narrowing the type is what lets a test
 * substitute a transport without asserting one type onto another.
 */
export type RunEventSource = EventTarget & { close(): void };

let eventSourceFactory: (url: string) => RunEventSource = (url) =>
  new EventSource(url);

/**
 * Swap the transport. Tests call this; nothing in the app does.
 *
 * jsdom implements `EventSource` and MSW does not intercept it, so without
 * a seam here a test that mounted a live screen would open a real
 * connection to a server that is not running. `src/test/setup.ts` installs
 * the fake for every test, so reaching the network is not something a test
 * can do by forgetting.
 */
export function setEventSourceFactory(
  factory: (url: string) => RunEventSource,
): void {
  eventSourceFactory = factory;
}

export function openRunEvents(runId: string): RunEventSource {
  return eventSourceFactory(`/api/runs/${encodeURIComponent(runId)}/events`);
}

/**
 * The lines one `log` frame carries, or none.
 *
 * A stream can be cut mid-frame by a server restart, and a parse error
 * there must cost one batch of log lines rather than the screen watching
 * the run. This is the second and last place the app turns untyped JSON
 * into a contract type, which is why it lives in this file with `apiGet`
 * rather than beside its caller.
 */
export function parseLogEvent(data: string): LogLine[] {
  try {
    const parsed: unknown = JSON.parse(data);
    return Array.isArray(parsed) ? (parsed as LogLine[]) : [];
  } catch {
    return [];
  }
}
