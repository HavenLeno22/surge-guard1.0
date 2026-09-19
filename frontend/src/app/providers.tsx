import { QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import type { ReactNode } from "react";
import { Toaster } from "sonner";

import { TooltipProvider } from "@/ui/Tooltip";
import { queryClient } from "./queryClient";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="user">
        <TooltipProvider delayDuration={250}>
          {children}
          <Toaster
            theme="dark"
            position="top-right"
            toastOptions={{
              style: {
                background: "var(--color-surface-2)",
                color: "var(--color-ink)",
                border: "1px solid var(--color-line-strong)",
                borderRadius: "var(--radius-control)",
                fontSize: "var(--text-sm)",
              },
            }}
          />
        </TooltipProvider>
      </MotionConfig>
    </QueryClientProvider>
  );
}
