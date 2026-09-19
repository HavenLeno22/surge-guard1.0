import { cn } from "@/lib/cn";

const SIZE_PX: Record<"sm" | "md" | "lg", number> = { sm: 14, md: 18, lg: 24 };

export function Spinner({
  size = "md",
  className,
}: {
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const px = SIZE_PX[size];
  return (
    <svg
      viewBox="0 0 24 24"
      width={px}
      height={px}
      className={cn("animate-spin motion-reduce:animate-none", className)}
      role="presentation"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9.5" fill="none" strokeWidth="2.5" className="stroke-ink-faint/35" />
      <path
        d="M21.5 12a9.5 9.5 0 0 0-9.5-9.5"
        fill="none"
        strokeWidth="2.5"
        strokeLinecap="round"
        className="stroke-current"
      />
    </svg>
  );
}
