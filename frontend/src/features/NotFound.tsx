import { Link } from "react-router";

import { Button } from "@/ui/Button";

export function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-center">
      <span className="readout text-5xl text-ink-faint">404</span>
      <h1 className="text-lg font-semibold text-ink-strong">Page not found</h1>
      <p className="max-w-sm text-sm text-ink-muted">
        That page does not exist, or has not been built yet.
      </p>
      <Button asChild variant="primary" className="mt-2">
        <Link to="/">Back to SurgeGuard</Link>
      </Button>
    </div>
  );
}
