import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { authApi } from "@/api/auth";
import { UNAUTHORIZED_EVENT } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AuthStatus } from "@/types/auth";

import { AuthGate } from "./AuthGate";

vi.mock("@/api/auth", () => ({ authApi: { status: vi.fn() } }));
// The socket is not under test; the gate's decisions are.
vi.mock("@/realtime/RealtimeProvider", () => ({
  RealtimeProvider: ({ children }: { children: ReactNode }) => children,
}));

const signedIn: AuthStatus = {
  auth_enabled: true,
  setup_required: false,
  user: {
    id: "user-1",
    email: "operator@example.test",
    display_name: "Operator",
    role: "OPERATOR",
    is_active: true,
    last_login_at: null,
    created_at: "2026-09-17T00:00:00Z",
  },
};

function renderGate(queryClient: QueryClient) {
  const router = createMemoryRouter(
    [
      { element: <AuthGate />, children: [{ path: "/command-center", element: <p>App content</p> }] },
      { path: "/login", element: <p>Sign-in page</p> },
    ],
    { initialEntries: ["/command-center"] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

function clientWith(status: AuthStatus | null): QueryClient {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // Cached long enough ago to be stale, so mounting the gate refetches it.
  if (status) queryClient.setQueryData(queryKeys.authStatus, status, { updatedAt: 0 });
  return queryClient;
}

describe("AuthGate", () => {
  beforeEach(() => {
    vi.mocked(authApi.status).mockReset();
  });

  test("keeps the app on screen when a background status refresh fails", async () => {
    vi.mocked(authApi.status).mockRejectedValue(new Error("Network down"));
    renderGate(clientWith(signedIn));

    await waitFor(() => expect(authApi.status).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(screen.getByText("App content")).toBeInTheDocument();
    expect(screen.queryByText("SurgeGuard is unreachable")).not.toBeInTheDocument();
  });

  test("says SurgeGuard is unreachable when the status was never loaded", async () => {
    vi.mocked(authApi.status).mockRejectedValue(new Error("Network down"));
    renderGate(clientWith(null));

    expect(await screen.findByText("SurgeGuard is unreachable")).toBeInTheDocument();
  });

  test("an unauthorised session goes to sign-in, remembering where it was", async () => {
    vi.mocked(authApi.status).mockResolvedValue(signedIn);
    renderGate(clientWith(signedIn));
    expect(await screen.findByText("App content")).toBeInTheDocument();

    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));

    expect(await screen.findByText("Sign-in page")).toBeInTheDocument();
  });
});
