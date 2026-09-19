import { AlertCircle } from "lucide-react";

import { cn } from "@/lib/cn";
import { Button } from "@/ui/Button";

export function ErrorState({
  title = "Something went wrong",
  description,
  onRetry,
  className,
}: {
  title?: string;
  description?: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center gap-2 py-10 text-center", className)}>
      <AlertCircle size={20} className="mb-1 text-critical-text" />
      <p className="text-sm font-medium text-ink-secondary">{title}</p>
      {description && <p className="max-w-sm text-xs text-ink-faint">{description}</p>}
      {onRetry && (
        <Button size="sm" variant="secondary" className="mt-2" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
