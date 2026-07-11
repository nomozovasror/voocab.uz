import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { ApiError, getErrorMessage } from "@/lib/api";
import { toast } from "@/lib/toast";

/**
 * Surface unexpected query/mutation failures as a toast so nothing fails
 * silently. Two cases are intentionally quiet:
 *  - 401s (the central client already redirects to login),
 *  - anything tagged `meta.suppressGlobalError` (e.g. the auth probe, which
 *    models "logged out" as data rather than an error).
 */
function reportError(error: unknown, suppress?: boolean): void {
  if (suppress) return;
  if (error instanceof ApiError && error.status === 401) return;
  toast(getErrorMessage(error));
}

/** Single shared QueryClient; wired into the app in app/providers.tsx. */
export const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) =>
      reportError(error, query.meta?.suppressGlobalError === true),
  }),
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) =>
      reportError(error, mutation.meta?.suppressGlobalError === true),
  }),
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
