import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export function SectionHeading({
  title,
  description,
  align = "left",
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  align?: "left" | "center";
  className?: string;
}) {
  return (
    <div className={cn("flex max-w-2xl flex-col gap-3", align === "center" && "mx-auto items-center text-center", className)}>
      <h2 className="text-2xl font-semibold text-ink-strong sm:text-3xl">{title}</h2>
      {description && <p className="text-base text-ink-muted">{description}</p>}
    </div>
  );
}
