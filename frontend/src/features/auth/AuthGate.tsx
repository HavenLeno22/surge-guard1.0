import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Navigate, Outlet, useLocation, useNavigate } from "react-router";

import { UNAUTHORIZED_EVENT } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { RealtimeProvider } from "@/realtime/RealtimeProvider";
import { Spinner } from "@/ui/Spinner";
import { Button } from "@/ui/Button";
import { useAuthStatus } from "./useAuthStatus";

function FullPageState({
  children,
}: {
  children: React.ReactNode;
}) {
  return <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-canvas px-6 text-center">{children}</div>;
}

/**
 * Decides landing/setup/login/app before anything behind it renders, and owns
 * the moment the Command Center socket is allowed to exist: only for a
 * session that is actually signed in (or auth is off entirely).
 */
export function AuthGate() {
  const { data: status, isPending, error, refetch } = useAuthStatus();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    function handleUnauthorized() {
      queryClient.invalidateQueries({ queryKey: queryKeys.authStatus });
      const next = `${location.pathname}${location.search}`;
      navigate(`/login?next=${encodeURIComponent(next)}`, { replace: true });
    }
    window.addEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
  }, [queryClient, navigate, location.pathname, location.search]);

  if (isPending) {
    return (
      <FullPageState>
        <Spinner size="lg" />
      </FullPageState>
    );
  }

  // Only when the status was never loaded. A failed background refresh keeps
  // the last known answer: the connection banner already reports an outage,
  // and replacing the whole Command Center during one would hide what is known.
  if (!status) {
    return (
      <FullPageState>
        <h1 className="text-lg font-semibold text-ink-strong">SurgeGuard is unreachable</h1>
        <p className="max-w-sm text-sm text-ink-muted">
          {error instanceof Error ? error.message : "Check that the backend is running."}
        </p>
        <Button variant="primary" onClick={() => refetch()}>
          Try again
        </Button>
      </FullPageState>
    );
  }

  if (status.auth_enabled) {
    if (status.setup_required) return <Navigate to="/setup" replace />;
    if (!status.user) {
      const next = `${location.pathname}${location.search}`;
      return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
    }
  }

  return (
    <RealtimeProvider>
      <Outlet />
    </RealtimeProvider>
  );
}
