import { Slot } from "radix-ui";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";
import type { ButtonVariant } from "./Button";

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "bg-ink-strong text-canvas hover:bg-ink disabled:bg-ink-faint/40 disabled:text-ink-faint",
  secondary:
    "border border-line-strong bg-transparent text-ink-secondary hover:bg-surface-2 hover:text-ink disabled:text-ink-faint",
  ghost: "bg-transparent text-ink-secondary hover:bg-surface-2 hover:text-ink disabled:text-ink-faint",
  danger: "bg-transparent text-critical-text hover:bg-critical/12 disabled:text-ink-faint",
};

const SIZE_CLASS: Record<"sm" | "md" | "lg", string> = {
  sm: "size-8 rounded-control",
  md: "size-9 rounded-control",
  lg: "size-11 rounded-control",
};

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  "aria-label": string;
  icon: ReactNode;
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  asChild?: boolean;
}

/** A button whose only content is an icon. `aria-label` is mandatory, not optional. */
export function IconButton({
  icon,
  variant = "ghost",
  size = "md",
  asChild = false,
  className,
  ref,
  ...props
}: IconButtonProps & { ref?: React.Ref<HTMLButtonElement> }) {
  const Comp = asChild ? Slot.Root : "button";
  return (
    <Comp
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center transition-colors duration-120 ease-out-soft",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-strong disabled:cursor-not-allowed disabled:opacity-40",
        VARIANT_CLASS[variant],
        SIZE_CLASS[size],
        className,
      )}
      {...props}
    >
      {icon}
    </Comp>
  );
}
