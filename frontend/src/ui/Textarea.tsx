import type { TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export function Textarea({
  className,
  rows = 3,
  ref,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { ref?: React.Ref<HTMLTextAreaElement> }) {
  return (
    <textarea
      ref={ref}
      rows={rows}
      className={cn(
        "w-full resize-y rounded-control border border-line-strong bg-surface-2 px-3 py-2 text-sm text-ink placeholder:text-ink-faint",
        "transition-colors duration-120 ease-out-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-strong",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "aria-invalid:border-critical",
        className,
      )}
      {...props}
    />
  );
}
