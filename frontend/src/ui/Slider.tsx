import { Slider as RadixSlider } from "radix-ui";

import { cn } from "@/lib/cn";

export function Slider({
  value,
  onValueChange,
  min = 0,
  max = 100,
  step = 1,
  disabled,
  className,
  "aria-label": ariaLabel,
}: {
  value: number;
  onValueChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  className?: string;
  "aria-label": string;
}) {
  return (
    <RadixSlider.Root
      value={[value]}
      onValueChange={([next]) => {
        if (next !== undefined) onValueChange(next);
      }}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      className={cn(
        "relative flex h-5 w-full touch-none items-center select-none",
        disabled && "opacity-40",
        className,
      )}
    >
      <RadixSlider.Track className="relative h-1 w-full grow overflow-hidden rounded-full bg-surface-3">
        <RadixSlider.Range className="absolute h-full bg-ink-strong" />
      </RadixSlider.Track>
      {/* The thumb carries role="slider", so the accessible name belongs on it, not the root. */}
      <RadixSlider.Thumb
        aria-label={ariaLabel}
        className={cn(
          "block size-4 rounded-full border-2 border-ink-strong bg-canvas",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-strong",
        )}
      />
    </RadixSlider.Root>
  );
}
