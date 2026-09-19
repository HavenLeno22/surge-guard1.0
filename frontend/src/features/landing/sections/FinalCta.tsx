import { Link } from "react-router";

import { Reveal } from "@/features/landing/Reveal";
import { Button } from "@/ui/Button";

export function FinalCta() {
  return (
    <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
      <Reveal className="flex flex-col items-center gap-5 rounded-lg border border-line bg-surface-1 px-6 py-16 text-center">
        <h2 className="display text-3xl text-ink-strong sm:text-4xl">
          See the pressure before it becomes an incident.
        </h2>
        <p className="max-w-lg text-sm text-ink-muted">
          Sign in to your control room's SurgeGuard deployment, or set one up on the cameras you
          already have.
        </p>
        <Button asChild variant="primary" size="lg">
          <Link to="/command-center">Open the Command Center</Link>
        </Button>
      </Reveal>
    </section>
  );
}
