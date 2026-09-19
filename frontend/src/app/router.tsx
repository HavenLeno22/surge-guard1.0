import { createBrowserRouter } from "react-router";

import { AuthGate } from "@/features/auth/AuthGate";
import { AppShell } from "@/features/shell/AppShell";
import { Spinner } from "@/ui/Spinner";
import { RouteError } from "./RouteError";

/** Shown while the first route's code is still loading; a plain canvas, not a flash of layout. */
function InitialLoad() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-canvas" aria-busy="true">
      <Spinner size="md" className="text-ink-faint" />
    </div>
  );
}

export const router = createBrowserRouter([
  {
    errorElement: <RouteError />,
    HydrateFallback: InitialLoad,
    children: [
      {
        path: "/",
        lazy: () => import("@/features/landing/LandingPage").then((m) => ({ Component: m.LandingPage })),
      },
      {
        path: "/login",
        lazy: () => import("@/features/auth/LoginPage").then((m) => ({ Component: m.LoginPage })),
      },
      {
        path: "/setup",
        lazy: () => import("@/features/auth/SetupPage").then((m) => ({ Component: m.SetupPage })),
      },
      {
        element: <AuthGate />,
        children: [
          {
            element: <AppShell />,
            children: [
              {
                path: "/command-center",
                lazy: () =>
                  import("@/features/command-center/CommandCenterPage").then((m) => ({
                    Component: m.CommandCenterPage,
                  })),
              },
              {
                path: "/cameras",
                lazy: () =>
                  import("@/features/cameras/CamerasPage").then((m) => ({ Component: m.CamerasPage })),
              },
              {
                path: "/cameras/:cameraId",
                lazy: () =>
                  import("@/features/cameras/detail/CameraDetailPage").then((m) => ({
                    Component: m.CameraDetailPage,
                  })),
              },
              {
                path: "/site",
                lazy: () => import("@/features/site/SitePage").then((m) => ({ Component: m.SitePage })),
              },
              {
                path: "/queues",
                lazy: () => import("@/features/queues/QueuesPage").then((m) => ({ Component: m.QueuesPage })),
              },
              {
                path: "/alerts",
                lazy: () => import("@/features/alerts/AlertsPage").then((m) => ({ Component: m.AlertsPage })),
              },
              {
                path: "/timeline",
                lazy: () => import("@/features/timeline/TimelinePage").then((m) => ({ Component: m.TimelinePage })),
              },
              {
                path: "/analytics",
                lazy: () => import("@/features/analytics/AnalyticsPage").then((m) => ({ Component: m.AnalyticsPage })),
              },
              {
                path: "/simulation",
                lazy: () =>
                  import("@/features/simulation/SimulationPage").then((m) => ({ Component: m.SimulationPage })),
              },
              {
                path: "/system",
                lazy: () => import("@/features/system/SystemPage").then((m) => ({ Component: m.SystemPage })),
              },
              {
                path: "/settings",
                lazy: () => import("@/features/settings/SettingsPage").then((m) => ({ Component: m.SettingsPage })),
              },
              {
                path: "/profile",
                lazy: () => import("@/features/profile/ProfilePage").then((m) => ({ Component: m.ProfilePage })),
              },
              {
                path: "*",
                lazy: () => import("@/features/NotFound").then((m) => ({ Component: m.NotFound })),
              },
            ],
          },
        ],
      },
    ],
  },
]);
