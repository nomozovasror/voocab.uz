import { QueryClient } from "@tanstack/react-query";

/** Single shared QueryClient; wired into the app in app/providers.tsx. */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
