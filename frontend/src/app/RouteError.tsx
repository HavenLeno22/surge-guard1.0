import { isRouteErrorResponse, useNavigate, useRouteError } from "react-router";

import { isApiError } from "@/api/client";
import { Button } from "@/ui/Button";

/** The last line of defence: a route threw, and something must still render. */
export function RouteError() {
  const error = useRouteError();
  const navigate = useNavigate();

  let title = "Something went wrong";
  let detail = "An unexpected error stopped this page from loading.";

  if (isRouteErrorResponse(error)) {
    title = error.status === 404 ? "Page not found" : `Error ${error.status}`;
    detail = error.statusText || detail;
  } else if (isApiError(error)) {
    title = error.isNetwork ? "SurgeGuard is unreachable" : "Request failed";
    detail = error.message;
  } else if (error instanceof Error) {
    detail = error.message;
  }

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-canvas px-6 text-center">
      <h1 className="text-xl font-semibold text-ink-strong">{title}</h1>
      <p className="max-w-sm text-sm text-ink-muted">{detail}</p>
      <div className="flex gap-3">
        <Button variant="secondary" onClick={() => navigate(-1)}>
          Go back
        </Button>
        <Button variant="primary" onClick={() => window.location.reload()}>
          Reload
        </Button>
      </div>
    </div>
  );
}
