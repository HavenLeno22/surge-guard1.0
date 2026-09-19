import { QueryClient } from "@tanstack/react-query";

import { isApiError } from "@/api/client";

function isRetryable(error: unknown): boolean {
  if (!isApiError(error)) return true;
  // Sign-in, permission and "does not exist" failures never change on retry.
  return !(error.isUnauthorized || error.isForbidden || error.isNotFound || error.isInvalid);
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => isRetryable(error) && failureCount < 2,
    },
    mutations: {
      retry: false,
    },
  },
});
