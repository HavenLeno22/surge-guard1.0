import { Hero } from "./hero/Hero";
import { LandingFooter } from "./LandingFooter";
import { LandingNav } from "./LandingNav";
import { GuidanceAnatomy } from "./sections/GuidanceAnatomy";
import { FinalCta } from "./sections/FinalCta";
import { Hardware } from "./sections/Hardware";
import { IndexExplorer } from "./sections/IndexExplorer";
import { Pipeline } from "./sections/Pipeline";
import { Precursors } from "./sections/Precursors";
import { Principles } from "./sections/Principles";
import { QueueLayers } from "./sections/QueueLayers";
import { SiteView } from "./sections/SiteView";

export function LandingPage() {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <LandingNav />
      <main>
        <Hero />
        <Precursors />
        <IndexExplorer />
        <Pipeline />
        <GuidanceAnatomy />
        <QueueLayers />
        <SiteView />
        <Hardware />
        <Principles />
        <FinalCta />
      </main>
      <LandingFooter />
    </div>
  );
}
