import { cn } from "@/lib/cn";

/**
 * The guard bar with three concentric arcs pressing on it (public/favicon.svg,
 * redrawn in currentColor so it inherits ink tones instead of a fixed fill).
 */
export function Logo({
  size = 24,
  withWordmark = false,
  className,
}: {
  size?: number;
  withWordmark?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5 text-ink-strong", className)}>
      <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
        <rect x="6.5" y="7" width="3" height="18" rx="1.5" fill="currentColor" />
        <path
          d="M14.81 23.71A12 12 0 0 1 14.81 8.29"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
        />
        <path
          d="M17.87 21.14A8 8 0 0 1 17.87 10.86"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          opacity="0.72"
        />
        <path
          d="M20.94 18.57A4 4 0 0 1 20.94 13.43"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          opacity="0.44"
        />
      </svg>
      {withWordmark && (
        <span className="text-base font-semibold tracking-tight text-ink-strong">SurgeGuard</span>
      )}
    </span>
  );
}
