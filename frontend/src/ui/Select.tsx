import { Check, ChevronDown } from "lucide-react";
import { Select as RadixSelect } from "radix-ui";

import { cn } from "@/lib/cn";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export function Select({
  value,
  onValueChange,
  options,
  placeholder = "Select…",
  disabled,
  id,
  className,
  "aria-label": ariaLabel,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  id?: string;
  className?: string;
  "aria-label"?: string;
}) {
  return (
    <RadixSelect.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <RadixSelect.Trigger
        id={id}
        aria-label={ariaLabel}
        className={cn(
          "flex h-9 w-full items-center justify-between gap-2 rounded-control border border-line-strong bg-surface-2 px-3 text-sm text-ink",
          "transition-colors duration-120 ease-out-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-strong",
          "disabled:cursor-not-allowed disabled:opacity-50 data-[placeholder]:text-ink-faint",
          className,
        )}
      >
        <RadixSelect.Value placeholder={placeholder} />
        <RadixSelect.Icon>
          <ChevronDown size={15} className="text-ink-muted" />
        </RadixSelect.Icon>
      </RadixSelect.Trigger>
      <RadixSelect.Portal>
        <RadixSelect.Content
          position="popper"
          sideOffset={6}
          className="z-50 max-h-72 overflow-hidden rounded-control border border-line-strong bg-surface-2 shadow-overlay"
        >
          <RadixSelect.Viewport className="p-1">
            {options.map((option) => (
              <RadixSelect.Item
                key={option.value}
                value={option.value}
                disabled={option.disabled}
                className={cn(
                  "flex cursor-pointer items-center justify-between gap-2 rounded-sm px-2.5 py-1.5 text-sm text-ink outline-none",
                  "data-[highlighted]:bg-surface-3 data-[disabled]:cursor-not-allowed data-[disabled]:text-ink-faint",
                )}
              >
                <RadixSelect.ItemText>{option.label}</RadixSelect.ItemText>
                <RadixSelect.ItemIndicator>
                  <Check size={14} className="text-ink-strong" />
                </RadixSelect.ItemIndicator>
              </RadixSelect.Item>
            ))}
          </RadixSelect.Viewport>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  );
}
