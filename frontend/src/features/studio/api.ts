import { api } from "@/lib/api";
import type { StudioListeningList, StudioStats } from "@/features/studio/types";

export const studioApi = {
  stats: () => api.get<StudioStats>("/api/studio/stats"),
  /** The author's own table of ONE paper. Under the skill rather than under
   *  /studio, because that is where the rest of a paper's API is. */
  papers: (skill: string) =>
    api.get<StudioListeningList>(`/api/${skill}/studio`),
};
