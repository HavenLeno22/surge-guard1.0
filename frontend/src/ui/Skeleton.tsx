import { cn } from "@/lib/cn";

/** A loading placeholder. Never used to imply a value - shape only, no digits. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn("skeleton rounded-sm", className)} />;
}
