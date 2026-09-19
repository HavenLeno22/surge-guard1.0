import { useAuthStatus } from "./useAuthStatus";

/** Mirrors the backend fallback (`auth/dependencies.py`): auth off means every request acts as ADMIN. */
export function useIsAdmin(): boolean {
  const { data: status } = useAuthStatus();
  if (!status) return false;
  return !status.auth_enabled || status.user?.role === "ADMIN";
}
