import { api } from "@/lib/api";
import type { StudioStats } from "@/features/studio/types";

export const studioApi = {
  stats: () => api.get<StudioStats>("/api/studio/stats"),
};
