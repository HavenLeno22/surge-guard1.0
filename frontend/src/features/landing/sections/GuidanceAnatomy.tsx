import { ActionList } from "@/components/intel/ActionList";
import { CausesList } from "@/components/intel/CausesList";
import { StatusPill } from "@/components/status/StatusPill";
import { exampleReport } from "@/features/landing/content";
import { Reveal } from "@/features/landing/Reveal";
import { SectionHeading } from "@/features/landing/SectionHeading";
import { formatCsi } from "@/lib/format";

export function GuidanceAnatomy() {
  return (
    <section id="guidance" className="border-t border-line bg-surface-1/40">
      <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
        <SectionHeading
          title="Guidance you can audit."
          description="Every recommendation traces to a rule id and to the measurements that triggered it - built from the app's own components."
        />
        <Reveal className="mt-10 rounded-lg border border-line bg-surface-1 p-6 sm:p-8">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <StatusPill status={exampleReport.status} />
              <span className="readout text-sm text-ink-secondary">
                CSI <span className="text-ink-strong">{formatCsi(exampleReport.csi)}</span>
              </span>
            </div>
            <span className="hatch rounded-xs border border-ink-strong/35 px-1.5 py-0.5 text-2xs font-medium text-ink-secondary">
              Example report
            </span>
          </div>
          <p className="text-sm text-ink">{exampleReport.situation_summary}</p>
          <div className="mt-6 grid gap-8 sm:grid-cols-2">
            <div>
              <h3 className="mb-3 text-xs font-medium text-ink-faint">Primary causes</h3>
              <CausesList causes={exampleReport.primary_causes} />
            </div>
            <div>
              <h3 className="mb-3 text-xs font-medium text-ink-faint">Recommended actions</h3>
              <ActionList actions={exampleReport.recommended_actions} />
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
