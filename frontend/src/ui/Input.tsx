import type { InputHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export function Input({
  className,
  ref,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { ref?: React.Ref<HTMLInputElement> }) {
  return (
    <input
      ref={ref}
      className={cn(
        "h-9 w-full rounded-control border border-line-strong bg-surface-2 px-3 text-sm text-ink placeholder:text-ink-faint",
        "transition-colors duration-120 ease-out-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-strong",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "aria-invalid:border-critical",
        className,
      )}
      {...props}
    />
  );
}
