import { useQuery } from "@tanstack/react-query";

import { authApi } from "@/api/auth";
import { queryKeys } from "@/api/queryKeys";

/** `/auth/status` is public and cheap: every gate decision starts here. */
export function useAuthStatus() {
  return useQuery({
    queryKey: queryKeys.authStatus,
    queryFn: ({ signal }) => authApi.status(signal),
    staleTime: 30_000,
  });
}
