import { useQueryClient } from "@tanstack/react-query";
import { LogOut, User as UserIcon } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { authApi } from "@/api/auth";
import { queryKeys } from "@/api/queryKeys";
import { useAuthStatus } from "@/features/auth/useAuthStatus";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/DropdownMenu";

export function UserMenu() {
  const { data: status } = useAuthStatus();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [signingOut, setSigningOut] = useState(false);
  const user = status?.user;

  async function handleSignOut() {
    setSigningOut(true);
    try {
      if (status?.auth_enabled) await authApi.logout();
    } catch {
      // The session is being abandoned regardless; a failed logout call
      // still ends locally, and the server-side session expires on its own.
    } finally {
      queryClient.setQueryData(queryKeys.authStatus, (prev: typeof status) =>
        prev ? { ...prev, user: null } : prev,
      );
      queryClient.clear();
      navigate("/login", { replace: true });
      setSigningOut(false);
    }
  }

  const initial = (user?.display_name ?? "?").trim().charAt(0).toUpperCase();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex size-8 items-center justify-center rounded-full border border-line-strong bg-surface-2 text-xs font-semibold text-ink-secondary transition-colors duration-120 ease-out-soft hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-strong"
          aria-label={user ? `Signed in as ${user.display_name}` : "Account"}
        >
          {user ? initial : <UserIcon size={15} />}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        {user && (
          <>
            <DropdownMenuLabel>
              <span className="block text-ink">{user.display_name}</span>
              <span className="block text-2xs font-normal text-ink-faint">
                {user.role === "ADMIN" ? "Administrator" : "Operator"}
              </span>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
          </>
        )}
        {status && !status.auth_enabled && (
          <DropdownMenuLabel>
            <span className="block text-ink">Sign-in is turned off</span>
            <span className="block max-w-56 text-2xs font-normal text-ink-faint">
              Everyone reaching this deployment acts as the control room operator.
            </span>
          </DropdownMenuLabel>
        )}
        {status?.auth_enabled && (
          <DropdownMenuItem onSelect={() => navigate("/profile")}>Profile & sessions</DropdownMenuItem>
        )}
        {status?.auth_enabled && (
          <DropdownMenuItem
            danger
            disabled={signingOut}
            onSelect={() => {
              void handleSignOut().catch(() => toast.error("Sign out failed."));
            }}
          >
            <LogOut size={14} />
            Sign out
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
