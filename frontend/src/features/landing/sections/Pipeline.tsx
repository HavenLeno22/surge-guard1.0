import { pipelineStages } from "@/features/landing/content";
import { Reveal } from "@/features/landing/Reveal";
import { SectionHeading } from "@/features/landing/SectionHeading";

export function Pipeline() {
  return (
    <section id="how-it-works" className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
      <SectionHeading
        title="How it works."
        description="Seven stages, running continuously per camera, from a raw frame to guidance an operator can audit."
      />
      <div className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-7 lg:gap-2">
        {pipelineStages.map((stage, index) => (
          <Reveal key={stage.title} delay={index * 0.04} className="relative">
            <div className="flex h-full flex-col gap-2 rounded-md border border-line bg-surface-1 p-4">
              <span className="readout text-xs text-ink-faint">{index + 1}</span>
              <h3 className="text-sm font-semibold text-ink-strong">{stage.title}</h3>
              <p className="text-xs text-ink-muted">{stage.detail}</p>
            </div>
            {index < pipelineStages.length - 1 && (
              <div className="pointer-events-none absolute top-1/2 right-0 hidden h-px w-2 -translate-y-1/2 translate-x-full bg-line-strong lg:block" />
            )}
          </Reveal>
        ))}
      </div>
    </section>
  );
}
