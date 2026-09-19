import { Switch as RadixSwitch } from "radix-ui";

import { cn } from "@/lib/cn";

export function Switch({
  checked,
  onCheckedChange,
  disabled,
  id,
  className,
  "aria-label": ariaLabel,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  id?: string;
  className?: string;
  "aria-label"?: string;
}) {
  return (
    <RadixSwitch.Root
      id={id}
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={ariaLabel}
      className={cn(
        "relative h-5 w-9 shrink-0 rounded-full border border-line-strong bg-surface-3 transition-colors duration-160 ease-out-soft",
        "data-[state=checked]:border-ink-strong/40 data-[state=checked]:bg-ink-strong",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-strong",
        "disabled:cursor-not-allowed disabled:opacity-40",
        className,
      )}
    >
      <RadixSwitch.Thumb
        className={cn(
          "block size-3.5 translate-x-0.5 rounded-full bg-ink-secondary transition-transform duration-160 ease-out-soft",
          "data-[state=checked]:translate-x-[18px] data-[state=checked]:bg-canvas",
        )}
      />
    </RadixSwitch.Root>
  );
}
