import { cn } from "@/lib/cn";
import { Spinner } from "@/ui/Spinner";

/** A 503: the component is still starting or between frames, not a failure. */
export function WaitingState({
  title = "Waiting for data",
  description,
  className,
}: {
  title?: string;
  description?: string;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center gap-2 py-10 text-center", className)}>
      <Spinner size="md" className="mb-1 text-ink-faint" />
      <p className="text-sm font-medium text-ink-secondary">{title}</p>
      {description && <p className="max-w-sm text-xs text-ink-faint">{description}</p>}
    </div>
  );
}
