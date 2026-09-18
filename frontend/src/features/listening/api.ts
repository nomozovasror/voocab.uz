import { api } from "@/lib/api";
import { paperApi, paperEndpoints } from "@/features/paper/api";
import type {
  AudioAssetDetail,
  AudioSegment,
} from "@/features/paper/types";

/**
 * The listening paper's client.
 *
 * Almost all of it is `paperApi` — the material tree, `/take`, attempts,
 * collections — because almost all of it is the same request whichever paper
 * is being sat. What is genuinely listening's is the skill-bound half, bound
 * here, and the transcript behind an uploaded recording, which is the one
 * thing reading has no counterpart for.
 */
export const listeningApi = {
  ...paperApi,
  ...paperEndpoints("listening"),

  // --- Editor support: the transcript source behind an uploaded clip -------
  audioAssets: {
    get: (assetId: string) => api.get<AudioAssetDetail>(`/api/audio-assets/${assetId}`),
    /** Corrects one transcript line for this owner. The recording's ASR rows
     *  are shared with anyone who uploaded the same bytes and are never
     *  touched; sending the original text back clears the correction. */
    updateSegment: (assetId: string, orderIndex: number, text: string) =>
      api.patch<AudioSegment>(
        `/api/audio-assets/${assetId}/segments/${orderIndex}`,
        { json: { text } },
      ),
  },
};

export { mediaUrl } from "@/features/paper/api";
