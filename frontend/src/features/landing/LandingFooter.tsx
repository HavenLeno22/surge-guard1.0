import { Link } from "react-router";

import { Logo } from "@/components/brand/Logo";

export function LandingFooter() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-10 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
        <div className="flex items-center gap-3">
          <Logo size={20} withWordmark />
          <span className="text-xs text-ink-faint">Crowd intelligence for control rooms.</span>
        </div>
        <nav className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-ink-muted">
          <a href="#how-it-works" className="hover:text-ink">How it works</a>
          <a href="#hardware" className="hover:text-ink">Hardware</a>
          <a href="#principles" className="hover:text-ink">Privacy &amp; principles</a>
          <Link to="/login" className="hover:text-ink">Sign in</Link>
        </nav>
      </div>
    </footer>
  );
}
