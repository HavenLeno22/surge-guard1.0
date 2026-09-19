import type { StreamLayer } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { LAYER_LABEL, LAYER_ORDER } from "@/lib/labels";
import { VisuallyHidden } from "@/ui/VisuallyHidden";

export function LayerToggle({
  value,
  onChange,
  className,
}: {
  value: StreamLayer[];
  onChange: (layers: StreamLayer[]) => void;
  className?: string;
}) {
  function toggle(layer: StreamLayer) {
    onChange(value.includes(layer) ? value.filter((l) => l !== layer) : [...value, layer]);
  }

  return (
    <fieldset className={cn("flex flex-wrap gap-1.5 border-0 p-0", className)}>
      <VisuallyHidden asChild>
        <legend>Video overlay layers</legend>
      </VisuallyHidden>
      {LAYER_ORDER.map((layer) => {
        const active = value.includes(layer);
        return (
          <button
            key={layer}
            type="button"
            aria-pressed={active}
            onClick={() => toggle(layer)}
            className={cn(
              "rounded-xs border px-2 py-1 text-2xs font-medium transition-colors duration-120 ease-out-soft",
              active
                ? "border-ink-strong/40 bg-ink-strong text-canvas"
                : "border-line-strong text-ink-muted hover:bg-surface-2 hover:text-ink",
            )}
          >
            {LAYER_LABEL[layer]}
          </button>
        );
      })}
    </fieldset>
  );
}
