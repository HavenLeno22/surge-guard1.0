import { Link } from "react-router";

import { Button } from "@/ui/Button";
import { VenueCanvas } from "./VenueCanvas";

export function Hero() {
  return (
    <section className="mx-auto flex max-w-7xl flex-col gap-10 px-4 pt-16 pb-8 sm:px-6 sm:pt-24 lg:flex-row lg:items-center lg:gap-14 lg:px-8 lg:pt-28">
      <div className="flex flex-1 flex-col gap-6">
        <h1 className="display text-4xl text-ink-strong sm:text-5xl lg:text-6xl">
          See pressure building in a crowd. Know exactly why.
        </h1>
        <p className="max-w-xl text-base text-ink-muted sm:text-lg">
          SurgeGuard turns the cameras a venue already has into a live Crowd Stability Index, queue
          forecasts and operator guidance — with every figure traceable to the measurement behind it.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Button asChild variant="primary" size="lg">
            <Link to="/command-center">Open the Command Center</Link>
          </Button>
          <Button asChild variant="secondary" size="lg">
            <a href="#how-it-works">How it works</a>
          </Button>
        </div>
      </div>
      <div className="flex-1">
        <VenueCanvas />
      </div>
    </section>
  );
}
