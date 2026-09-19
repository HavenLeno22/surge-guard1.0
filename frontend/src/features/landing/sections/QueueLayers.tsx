import { ClipboardList, TrendingUp, Users } from "lucide-react";

import { Reveal } from "@/features/landing/Reveal";
import { SectionHeading } from "@/features/landing/SectionHeading";

const LAYERS = [
  {
    icon: Users,
    title: "Now",
    detail:
      "How the queue formed, counted arrival and service rates, and an honest wait - never a number when nobody is being served.",
  },
  {
    icon: TrendingUp,
    title: "Next",
    detail:
      "Two independent forecast methods plus their consensus and how much they agree, out to fifteen minutes.",
  },
  {
    icon: ClipboardList,
    title: "What to do",
    detail:
      "A capacity ladder: the projected queue and wait at every counter count the planner tried, and whether the target is even reachable.",
  },
] as const;

export function QueueLayers() {
  return (
    <section id="queues" className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
      <SectionHeading
        title="Queues: now, next, and what to do."
        description="Three separated layers, so an operator never mistakes a forecast for a measurement, or an assumption for a fact."
      />
      <div className="mt-10 grid gap-4 sm:grid-cols-3">
        {LAYERS.map((layer, index) => (
          <Reveal key={layer.title} delay={index * 0.06}>
            <div className="flex h-full flex-col gap-3 rounded-md border border-line bg-surface-1 p-5">
              <layer.icon size={18} className="text-ink-secondary" />
              <h3 className="text-sm font-semibold text-ink-strong">{layer.title}</h3>
              <p className="text-xs text-ink-muted">{layer.detail}</p>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}
