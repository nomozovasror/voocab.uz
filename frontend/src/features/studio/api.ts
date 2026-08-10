import { api } from "@/lib/api";
import type { StudioListeningList, StudioStats } from "@/features/studio/types";

export const studioApi = {
  stats: () => api.get<StudioStats>("/api/studio/stats"),
  listening: () => api.get<StudioListeningList>("/api/studio/listening"),
};
