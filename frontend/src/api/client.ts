/**
 * The REST client.
 *
 * Every response uses the backend envelope `{status, message, data, error_code}`.
 * This unwraps `data` and turns every failure into an `ApiError` whose getters
 * say what kind of failure it is - because the interface must treat them
 * differently: a 503 is a component still starting (show "waiting"), a network
 * failure is the backend unreachable, a 401 means sign in again.
 *
 * Requests go to the page's own origin with the session cookie. No token ever
 * touches JavaScript.
 */

export const API_BASE = "/api/v1";

/** Fired on `window` when an authenticated request is refused with 401. */
export const UNAUTHORIZED_EVENT = "surgeguard:unauthorized";

const DEFAULT_TIMEOUT_MS = 10_000;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly retryAfterSeconds: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** The backend could not be reached at all, or a proxy could not reach it. */
  get isNetwork(): boolean {
    return (
      this.status === 0 ||
      this.status === 502 ||
      this.status === 504 ||
      this.code === "BACKEND_UNREACHABLE"
    );
  }

  /** A component is temporarily unavailable - a waiting state, not a failure. */
  get isUnavailable(): boolean {
    return this.status === 503;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  get isConflict(): boolean {
    return this.status === 409;
  }

  get isInvalid(): boolean {
    return this.status === 400 || this.status === 422;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, QueryValue>;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export interface Enveloped<T> {
  data: T;
  message: string;
}

export function apiUrl(path: string, query?: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== null && value !== undefined) search.set(key, String(value));
  }
  const suffix = search.toString();
  return `${API_BASE}${path}${suffix ? `?${suffix}` : ""}`;
}

function defaultMessage(status: number): string {
  if (status === 401) return "Sign in to continue.";
  if (status === 403) return "Your role does not allow this change.";
  if (status === 404) return "That was not found.";
  if (status === 503) return "This part of SurgeGuard is not available yet.";
  if (status >= 500) return "The SurgeGuard backend could not be reached.";
  return "The request could not be completed.";
}

/** Perform a request and return the envelope's data and message. */
export async function apiRequestEnvelope<T>(
  path: string,
  { method = "GET", body, query, signal, timeoutMs = DEFAULT_TIMEOUT_MS }: RequestOptions = {},
): Promise<Enveloped<T>> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const forwardAbort = () => controller.abort();
  signal?.addEventListener("abort", forwardAbort, { once: true });

  let response: Response;
  try {
    response = await fetch(apiUrl(path, query), {
      method,
      credentials: "same-origin",
      headers:
        body === undefined
          ? { Accept: "application/json" }
          : { Accept: "application/json", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error; // cancelled by the caller: not a failure to report
    throw new ApiError(
      0,
      timedOut ? "TIMEOUT" : "NETWORK_ERROR",
      timedOut
        ? "The SurgeGuard backend did not answer in time."
        : "The SurgeGuard backend could not be reached. Check that it is running.",
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", forwardAbort);
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  const envelope =
    payload !== null && typeof payload === "object"
      ? (payload as { message?: unknown; error_code?: unknown; data?: unknown })
      : null;

  if (!response.ok) {
    const hasEnvelope = envelope !== null && typeof envelope.error_code === "string";
    const code = hasEnvelope
      ? (envelope.error_code as string)
      : response.status >= 500
        ? "BACKEND_UNREACHABLE"
        : "HTTP_ERROR";
    const message =
      hasEnvelope && typeof envelope.message === "string"
        ? envelope.message
        : defaultMessage(response.status);
    const retryAfter = Number(response.headers.get("Retry-After"));
    if (response.status === 401 && !path.startsWith("/auth/")) {
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    }
    throw new ApiError(
      response.status,
      code,
      message,
      Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
    );
  }

  if (envelope !== null && "data" in envelope) {
    return {
      data: envelope.data as T,
      message: typeof envelope.message === "string" ? envelope.message : "",
    };
  }
  // The liveness and readiness probes answer without an envelope.
  return { data: payload as T, message: "" };
}

/** Perform a request and return the envelope's data. */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return (await apiRequestEnvelope<T>(path, options)).data;
}
