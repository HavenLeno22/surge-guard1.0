import { afterEach, describe, expect, test, vi } from "vitest";

import { ApiError, apiRequest, apiUrl, UNAUTHORIZED_EVENT } from "./client";

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  return vi.fn().mockResolvedValue(
    new Response(typeof body === "string" ? body : JSON.stringify(body), { status, headers }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiRequest", () => {
  test("unwraps the envelope's data and sends the session cookie", async () => {
    const fetchMock = respond(200, { status: "success", message: "ok", data: { total: 2 } });
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/cameras")).resolves.toEqual({ total: 2 });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe("same-origin");
  });

  test("a 503 is a waiting state, not a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      respond(503, {
        status: "error",
        message: "No analysis yet.",
        error_code: "SERVICE_UNAVAILABLE",
        data: null,
      }),
    );

    const error = (await apiRequest("/intelligence/current").catch((caught) => caught)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.isUnavailable).toBe(true);
    expect(error.isNetwork).toBe(false);
    expect(error.message).toBe("No analysis yet.");
  });

  test("an unreachable backend is a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const error = (await apiRequest("/cameras").catch((caught) => caught)) as ApiError;
    expect(error.isNetwork).toBe(true);
    expect(error.status).toBe(0);
  });

  test("a proxy error page without an envelope is treated as unreachable", async () => {
    vi.stubGlobal("fetch", respond(500, "Error occurred while trying to proxy"));

    const error = (await apiRequest("/cameras").catch((caught) => caught)) as ApiError;
    expect(error.isNetwork).toBe(true);
  });

  test("a 401 on an operational route announces that sign-in is needed", async () => {
    vi.stubGlobal(
      "fetch",
      respond(401, { status: "error", message: "Sign in.", error_code: "UNAUTHORIZED", data: null }),
    );
    const listener = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, listener);

    await apiRequest("/cameras").catch(() => undefined);
    await apiRequest("/auth/login", { method: "POST", body: {} }).catch(() => undefined);

    window.removeEventListener(UNAUTHORIZED_EVENT, listener);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  test("a lockout carries how long to wait", async () => {
    vi.stubGlobal(
      "fetch",
      respond(
        429,
        { status: "error", message: "Wait.", error_code: "TOO_MANY_ATTEMPTS", data: null },
        { "Retry-After": "42" },
      ),
    );

    const error = (await apiRequest("/auth/login", { method: "POST", body: {} }).catch(
      (e) => e,
    )) as ApiError;
    expect(error.code).toBe("TOO_MANY_ATTEMPTS");
    expect(error.retryAfterSeconds).toBe(42);
  });

  test("query values that are not set are left out of the URL", () => {
    expect(apiUrl("/history/site", { from: "a", to: undefined, resolution: null })).toBe(
      "/api/v1/history/site?from=a",
    );
  });
});
