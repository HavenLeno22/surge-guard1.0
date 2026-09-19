import { useMemo, useState } from "react";

import { BandScale } from "@/components/brand/BandScale";
import { stabilityIndex } from "@/features/landing/hero/venueSim";
import { Reveal } from "@/features/landing/Reveal";
import { SectionHeading } from "@/features/landing/SectionHeading";
import { formatCsi } from "@/lib/format";
import { INDICATOR_DEFAULT_WEIGHT, INDICATOR_LABEL, INDICATOR_ORDER, STATUS_LABEL } from "@/lib/labels";
import { statusFromCsi } from "@/lib/status";
import { Slider } from "@/ui/Slider";
import { Switch } from "@/ui/Switch";
import type { StabilityIndicator } from "@/types/contracts";

const DEFAULT_PRESSURE: Record<StabilityIndicator, number> = {
  DENSITY_PRESSURE: 35,
  MOTION_SUPPRESSION: 20,
  EGRESS_CONGESTION: 15,
  FLOW_CONFLICT: 10,
  RATE_OF_CHANGE: 10,
};

export function IndexExplorer() {
  const [pressure, setPressure] = useState(DEFAULT_PRESSURE);
  const [available, setAvailable] = useState<Record<StabilityIndicator, boolean>>({
    DENSITY_PRESSURE: true,
    MOTION_SUPPRESSION: true,
    EGRESS_CONGESTION: true,
    FLOW_CONFLICT: true,
    RATE_OF_CHANGE: true,
  });

  const csi = useMemo(
    () => stabilityIndex(pressure, INDICATOR_DEFAULT_WEIGHT, available),
    [pressure, available],
  );
  const status = statusFromCsi(csi);

  return (
    <section id="index" className="border-t border-line bg-surface-1/40">
      <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
        <SectionHeading
          title="The index, explained by touching it."
          description="The real weights, the real formula, and what happens when an indicator drops out."
        />
        <div className="mt-10 grid gap-10 lg:grid-cols-2 lg:items-center">
          <Reveal className="flex flex-col gap-5">
            {INDICATOR_ORDER.map((indicator) => (
              <div key={indicator} className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm text-ink-secondary">{INDICATOR_LABEL[indicator]}</span>
                  <div className="flex items-center gap-2">
                    <span className="readout text-xs text-ink-faint">
                      {available[indicator] ? Math.round(pressure[indicator]) : "—"}
                    </span>
                    <Switch
                      aria-label={`${INDICATOR_LABEL[indicator]} available`}
                      checked={available[indicator]}
                      onCheckedChange={(checked) =>
                        setAvailable((prev) => ({ ...prev, [indicator]: checked }))
                      }
                    />
                  </div>
                </div>
                <Slider
                  aria-label={`${INDICATOR_LABEL[indicator]} pressure`}
                  value={pressure[indicator]}
                  onValueChange={(value) => setPressure((prev) => ({ ...prev, [indicator]: value }))}
                  disabled={!available[indicator]}
                />
              </div>
            ))}
          </Reveal>
          <Reveal delay={0.1} className="rounded-lg border border-line bg-surface-1 p-8">
            <div className="flex flex-col items-center gap-4 text-center">
              <span className="text-xs text-ink-faint">Crowd Stability Index</span>
              <span className="readout text-6xl text-ink-strong">{formatCsi(csi)}</span>
              <span className="text-sm text-ink-secondary">{STATUS_LABEL[status]}</span>
              <BandScale value={csi} className="w-full max-w-xs" />
              <p className="mt-2 max-w-xs text-xs text-ink-faint">
                CSI = 100 − Σ(weight × pressure), renormalised across whichever indicators are
                available.
              </p>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
