import { Menu } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";

import { Logo } from "@/components/brand/Logo";
import { useAuthStatus } from "@/features/auth/useAuthStatus";
import { cn } from "@/lib/cn";
import { Button } from "@/ui/Button";
import { Drawer } from "@/ui/Drawer";
import { IconButton } from "@/ui/IconButton";

const LINKS = [
  { href: "#how-it-works", label: "How it works" },
  { href: "#guidance", label: "Guidance" },
  { href: "#queues", label: "Queues" },
  { href: "#site", label: "Site" },
  { href: "#hardware", label: "Hardware" },
];

function useScrolled(threshold: number): boolean {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    function onScroll() {
      setScrolled(window.scrollY > threshold);
    }
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [threshold]);
  return scrolled;
}

export function LandingNav() {
  const scrolled = useScrolled(24);
  const { data: status } = useAuthStatus();
  const [mobileOpen, setMobileOpen] = useState(false);
  const signedIn = Boolean(status?.user) || status?.auth_enabled === false;

  return (
    <header
      className={cn(
        "sticky top-0 z-40 transition-colors duration-160 ease-out-soft",
        scrolled ? "border-b border-line bg-canvas/80 backdrop-blur-md" : "border-b border-transparent",
      )}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link to="/" className="flex items-center">
          <Logo size={24} withWordmark />
        </Link>
        <nav className="hidden items-center gap-6 lg:flex">
          {LINKS.map((link) => (
            <a key={link.href} href={link.href} className="text-sm text-ink-secondary hover:text-ink">
              {link.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <Button asChild variant="primary" size="sm" className="hidden sm:inline-flex">
            <Link to={signedIn ? "/command-center" : "/login"}>
              {signedIn ? "Open the Command Center" : "Sign in"}
            </Link>
          </Button>
          <IconButton
            aria-label="Open menu"
            icon={<Menu size={18} />}
            className="lg:hidden"
            onClick={() => setMobileOpen(true)}
          />
        </div>
      </div>

      <Drawer open={mobileOpen} onOpenChange={setMobileOpen} title="Menu" side="right">
        <nav className="flex flex-col gap-1">
          {LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              onClick={() => setMobileOpen(false)}
              className="rounded-control px-2 py-2.5 text-sm text-ink-secondary hover:bg-surface-2 hover:text-ink"
            >
              {link.label}
            </a>
          ))}
          <Button asChild variant="primary" className="mt-3">
            <Link to={signedIn ? "/command-center" : "/login"} onClick={() => setMobileOpen(false)}>
              {signedIn ? "Open the Command Center" : "Sign in"}
            </Link>
          </Button>
        </nav>
      </Drawer>
    </header>
  );
}
