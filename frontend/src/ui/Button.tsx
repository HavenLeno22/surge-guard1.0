import { Slot } from "radix-ui";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";
import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary:
    "bg-ink-strong text-canvas hover:bg-ink disabled:bg-ink-faint/40 disabled:text-ink-faint",
  secondary:
    "border border-line-strong bg-transparent text-ink hover:bg-surface-2 disabled:border-line disabled:text-ink-faint",
  ghost: "bg-transparent text-ink-secondary hover:bg-surface-2 hover:text-ink disabled:text-ink-faint",
  danger: "bg-critical text-ink-strong hover:bg-critical/85 disabled:bg-critical/30",
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 rounded-control px-2.5 text-xs",
  md: "h-9 gap-2 rounded-control px-3.5 text-sm",
  lg: "h-11 gap-2 rounded-control px-5 text-base",
};

const BASE_CLASS =
  "inline-flex select-none items-center justify-center whitespace-nowrap font-medium transition-colors duration-120 ease-out-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-strong disabled:cursor-not-allowed";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  iconStart?: ReactNode;
  iconEnd?: ReactNode;
  /** Merge these props onto the single child element instead of rendering a `<button>`. Icons and the loading spinner are not injected in this mode - put them inside the child yourself. */
  asChild?: boolean;
}

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  iconStart,
  iconEnd,
  asChild = false,
  disabled,
  className,
  children,
  ref,
  ...props
}: ButtonProps & { ref?: React.Ref<HTMLButtonElement> }) {
  const classes = cn(BASE_CLASS, VARIANT_CLASS[variant], SIZE_CLASS[size], className);

  if (asChild) {
    return (
      <Slot.Root ref={ref} className={classes} {...props}>
        {children}
      </Slot.Root>
    );
  }

  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={classes}
      {...props}
    >
      {loading ? <Spinner size={size === "lg" ? "md" : "sm"} /> : iconStart}
      {children}
      {!loading && iconEnd}
    </button>
  );
}
