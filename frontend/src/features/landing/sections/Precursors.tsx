import { precursors } from "@/features/landing/content";
import { Reveal } from "@/features/landing/Reveal";
import { SectionHeading } from "@/features/landing/SectionHeading";

export function Precursors() {
  return (
    <section id="precursors" className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
      <SectionHeading
        title="A crowd rarely fails all at once."
        description="Five measurable precursors, tracked continuously, long before a situation is obvious to the eye."
      />
      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {precursors.map((item, index) => (
          <Reveal key={item.title} delay={index * 0.05}>
            <div className="flex h-full flex-col gap-2 rounded-md border border-line bg-surface-1 p-4">
              <span className="readout text-xs text-ink-faint">0{index + 1}</span>
              <h3 className="text-sm font-semibold text-ink-strong">{item.title}</h3>
              <p className="text-xs text-ink-muted">{item.description}</p>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}
