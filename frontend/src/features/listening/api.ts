import { apiUrl } from "@/config";
import { ApiError, api } from "@/lib/api";
import type { RequestOptions } from "@/lib/api";
import type {
  AudioSegment,
  AttemptResult,
  AttemptSubmit,
  AudioAssetDetail,
  AudioUpload,
  ListeningMaterial,
  ListeningMaterialCreate,
  ListeningMaterialDetail,
  ListeningMaterialUpdate,
  ListeningQuestionGroup,
  MaterialTake,
  PartCreate,
  PartOut,
  PartUpdate,
  QuestionGroupIn,
} from "@/features/listening/types";

/** Resolve a stored audio URL for playback: absolute (R2) as-is, relative
 *  (local /media/…) against the API origin. */
export function mediaUrl(url: string): string {
  return /^https?:\/\//.test(url) ? url : apiUrl(url);
}

/** Upload an audio clip; returns the asset to attach to a material. */
async function uploadAudio(file: File): Promise<AudioUpload> {
  const form = new FormData();
  form.append("file", file);
  let res: Response;
  try {
    res = await fetch(apiUrl("/api/uploads/audio"), {
      method: "POST",
      credentials: "include",
      body: form, // browser sets multipart Content-Type + boundary
    });
  } catch {
    throw new ApiError(0, "Network error. Check your connection and try again.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail || "Upload failed");
  }
  return (await res.json()) as AudioUpload;
}

export const listeningApi = {
  uploadAudio,

  materials: {
    list: (scope: "mine" | "public" = "mine") =>
      api.get<ListeningMaterial[]>("/api/materials", { params: { scope } }),
    get: (id: string) => api.get<ListeningMaterialDetail>(`/api/materials/${id}`),
    create: (data: ListeningMaterialCreate) =>
      api.post<ListeningMaterialDetail>("/api/materials", { json: data }),
    update: (
      id: string,
      data: ListeningMaterialUpdate,
      opts?: RequestOptions,
    ) =>
      api.patch<ListeningMaterialDetail>(`/api/materials/${id}`, {
        ...opts,
        json: data,
      }),
    remove: (id: string) => api.delete<void>(`/api/materials/${id}`),
  },

  parts: {
    create: (materialId: string, data: PartCreate, opts?: RequestOptions) =>
      api.post<PartOut>(`/api/materials/${materialId}/parts`, {
        ...opts,
        json: data,
      }),
    update: (partId: string, data: PartUpdate, opts?: RequestOptions) =>
      api.patch<PartOut>(`/api/parts/${partId}`, { ...opts, json: data }),
    remove: (partId: string, opts?: RequestOptions) =>
      api.delete<void>(`/api/parts/${partId}`, opts),
  },

  questionGroups: {
    create: (partId: string, data: QuestionGroupIn, opts?: RequestOptions) =>
      api.post<ListeningQuestionGroup>(`/api/parts/${partId}/question-groups`, {
        ...opts,
        json: data,
      }),
    update: (groupId: string, data: QuestionGroupIn, opts?: RequestOptions) =>
      api.patch<ListeningQuestionGroup>(`/api/question-groups/${groupId}`, {
        ...opts,
        json: data,
      }),
    remove: (groupId: string, opts?: RequestOptions) =>
      api.delete<void>(`/api/question-groups/${groupId}`, opts),
    /** The part's groups in their new order — all of them, by id. A move is
     *  sent as the whole order rather than as a direction, so two windows
     *  can't interleave two half-moves into an order neither asked for. */
    reorder: (partId: string, groupIds: string[], opts?: RequestOptions) =>
      api.put<ListeningQuestionGroup[]>(
        `/api/parts/${partId}/question-groups/order`,
        { ...opts, json: { group_ids: groupIds } },
      ),
  },

  // --- Consumption (§8): the ONLY read path the take/practice UI may use.
  // Never call materials.get() (the author endpoint) from consumption code —
  // it carries correct_answers. `take` is structurally guaranteed answer-free
  // (backend's TakeQuestionOut has no such field at all).
  take: (materialId: string) =>
    api.get<MaterialTake>(`/api/materials/${materialId}/take`),

  submitAttempt: (materialId: string, data: AttemptSubmit) =>
    api.post<AttemptResult>(`/api/materials/${materialId}/attempts`, {
      json: data,
    }),

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
