import { useQuery } from "@tanstack/react-query";
import { studioApi } from "@/features/studio/api";

export function useStudioStats() {
  return useQuery({
    queryKey: ["studio-stats"] as const,
    queryFn: studioApi.stats,
  });
}

const PENDING_TRANSCRIPT_STATES = new Set(["pending", "processing"]);

export function useStudioListening() {
  return useQuery({
    queryKey: ["studio-listening"] as const,
    queryFn: studioApi.listening,
    // While any row's transcript is still being produced, poll modestly so
    // the row updates itself once it lands — stop entirely once nothing is
    // pending (no point polling a fully-settled list).
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const hasPending = data.items.some(
        (item) =>
          item.transcript_status != null &&
          PENDING_TRANSCRIPT_STATES.has(item.transcript_status),
      );
      return hasPending ? 4000 : false;
    },
  });
}
