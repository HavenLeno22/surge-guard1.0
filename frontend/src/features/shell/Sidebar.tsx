import {
  Activity,
  AlertTriangle,
  BarChart3,
  Camera,
  FlaskConical,
  History,
  LayoutDashboard,
  ListOrdered,
  Map as MapIcon,
  Settings as SettingsIcon,
} from "lucide-react";
import type { ComponentType } from "react";
import { NavLink } from "react-router";

import { cn } from "@/lib/cn";
import { useLive } from "@/realtime/store";
import { Logo } from "@/components/brand/Logo";

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<{ size?: number }>;
  badge?: number;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

function useNavGroups(): NavGroup[] {
  const alertCount = useLive((state) => state.site?.alerts.length ?? 0);
  return [
    {
      label: "Live",
      items: [
        { to: "/command-center", label: "Command Center", icon: LayoutDashboard },
        { to: "/site", label: "Site", icon: MapIcon },
        { to: "/queues", label: "Queues", icon: ListOrdered },
        { to: "/alerts", label: "Alerts", icon: AlertTriangle, badge: alertCount },
        { to: "/timeline", label: "Timeline", icon: History },
      ],
    },
    { label: "Network", items: [{ to: "/cameras", label: "Cameras", icon: Camera }] },
    {
      label: "Insight",
      items: [
        { to: "/analytics", label: "Analytics", icon: BarChart3 },
        { to: "/simulation", label: "Simulation", icon: FlaskConical },
      ],
    },
    {
      label: "Platform",
      items: [
        { to: "/system", label: "System", icon: Activity },
        { to: "/settings", label: "Settings", icon: SettingsIcon },
      ],
    },
  ];
}

export function Sidebar({ onNavigate, className }: { onNavigate?: () => void; className?: string }) {
  const groups = useNavGroups();
  return (
    <nav className={cn("flex h-full flex-col gap-6 overflow-y-auto px-3 py-5", className)}>
      <div className="px-2">
        <Logo size={24} withWordmark />
      </div>
      {groups.map((group) => (
        <div key={group.label} className="flex flex-col gap-1">
          <span className="px-2 text-2xs font-medium text-ink-faint">{group.label}</span>
          {group.items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  "flex items-center justify-between gap-2 rounded-control px-2.5 py-2 text-sm transition-colors duration-120 ease-out-soft",
                  isActive
                    ? "bg-surface-2 text-ink-strong"
                    : "text-ink-secondary hover:bg-surface-2/60 hover:text-ink",
                )
              }
            >
              <span className="flex items-center gap-2.5">
                <item.icon size={16} />
                {item.label}
              </span>
              {!!item.badge && (
                <span className="rounded-full bg-critical/15 px-1.5 py-0.5 text-2xs font-semibold text-critical-text">
                  {item.badge}
                </span>
              )}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );
}
