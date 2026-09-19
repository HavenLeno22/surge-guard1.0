import { hardwareFacts } from "@/features/landing/content";
import { Reveal } from "@/features/landing/Reveal";
import { SectionHeading } from "@/features/landing/SectionHeading";

export function Hardware() {
  return (
    <section id="hardware" className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
      <SectionHeading
        title="Cameras you already have."
        description="No proprietary hardware. SurgeGuard fits the sensors a venue already owns."
      />
      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {hardwareFacts.map((fact, index) => (
          <Reveal key={fact.title} delay={index * 0.05}>
            <div className="flex h-full flex-col gap-2 rounded-md border border-line bg-surface-1 p-5">
              <h3 className="text-sm font-semibold text-ink-strong">{fact.title}</h3>
              <p className="text-xs text-ink-muted">{fact.detail}</p>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}
