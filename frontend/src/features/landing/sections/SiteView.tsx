import { GitBranch, Map, TrendingDown } from "lucide-react";

import { Reveal } from "@/features/landing/Reveal";
import { SectionHeading } from "@/features/landing/SectionHeading";

const FACTS = [
  {
    icon: Map,
    title: "Overlap-aware counting",
    detail:
      "Where two cameras share coverage, the site headcount takes the larger single count for that area and reports the sum as an honest upper bound - never double-counted.",
  },
  {
    icon: GitBranch,
    title: "Tracked versus correlated flow",
    detail:
      "Movement within one camera is tracked directly. Movement between cameras is correlated from exit and entry rates, and drawn differently on the flow map.",
  },
  {
    icon: TrendingDown,
    title: "Withheld, not estimated",
    detail:
      "A site-wide forecast or staffing plan is withheld, with the reason shown, whenever coverage is incomplete.",
  },
] as const;

export function SiteView() {
  return (
    <section id="site" className="border-t border-line bg-surface-1/40">
      <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
        <SectionHeading
          title="Every camera, one site."
          description="Individual cameras roll up into one picture of the venue, without pretending to see more than it does."
        />
        <div className="mt-10 grid gap-4 sm:grid-cols-3">
          {FACTS.map((fact, index) => (
            <Reveal key={fact.title} delay={index * 0.06}>
              <div className="flex h-full flex-col gap-3 rounded-md border border-line bg-surface-1 p-5">
                <fact.icon size={18} className="text-ink-secondary" />
                <h3 className="text-sm font-semibold text-ink-strong">{fact.title}</h3>
                <p className="text-xs text-ink-muted">{fact.detail}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
