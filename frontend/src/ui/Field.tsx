import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export function Field({
  label,
  htmlFor,
  help,
  error,
  required = false,
  className,
  children,
}: {
  label: string;
  htmlFor: string;
  help?: string;
  error?: string | null;
  required?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const helpId = help ? `${htmlFor}-help` : undefined;
  const errorId = error ? `${htmlFor}-error` : undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={htmlFor} className="text-xs font-medium text-ink-secondary">
        {label}
        {required && <span className="text-critical-text"> *</span>}
      </label>
      {children}
      {help && !error && (
        <p id={helpId} className="text-xs text-ink-faint">
          {help}
        </p>
      )}
      {error && (
        <p id={errorId} role="alert" className="text-xs text-critical-text">
          {error}
        </p>
      )}
    </div>
  );
}

/** The `aria-describedby`/`aria-invalid` pair a Field's control should carry. */
export function fieldControlProps(
  htmlFor: string,
  { help, error }: { help?: string; error?: string | null },
): { id: string; "aria-describedby"?: string; "aria-invalid"?: true } {
  const describedBy = error ? `${htmlFor}-error` : help ? `${htmlFor}-help` : undefined;
  return {
    id: htmlFor,
    ...(describedBy ? { "aria-describedby": describedBy } : {}),
    ...(error ? { "aria-invalid": true as const } : {}),
  };
}
