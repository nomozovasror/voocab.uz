import { useQuery } from "@tanstack/react-query";
import { studioApi } from "@/features/studio/api";

export function useStudioStats() {
  return useQuery({
    queryKey: ["studio-stats"] as const,
    queryFn: studioApi.stats,
  });
}
