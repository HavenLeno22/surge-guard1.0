import type { ReactNode } from "react";
import { Link } from "react-router";

import { Logo } from "@/components/brand/Logo";

export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="hairline-grid flex min-h-dvh items-center justify-center bg-canvas px-4 py-12">
      <div className="w-full max-w-sm">
        <Link to="/" className="mb-8 flex items-center justify-center">
          <Logo size={28} withWordmark />
        </Link>
        <div className="rounded-lg border border-line bg-surface-1 p-7 shadow-overlay">
          <h1 className="text-lg font-semibold text-ink-strong">{title}</h1>
          <p className="mt-1.5 text-sm text-ink-muted">{subtitle}</p>
          <div className="mt-6">{children}</div>
        </div>
        {footer && <div className="mt-5 text-center text-xs text-ink-faint">{footer}</div>}
      </div>
    </div>
  );
}
