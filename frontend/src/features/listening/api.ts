import { apiUrl } from "@/config";
import { ApiError, api } from "@/lib/api";
import type {
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
    update: (id: string, data: ListeningMaterialUpdate) =>
      api.patch<ListeningMaterialDetail>(`/api/materials/${id}`, { json: data }),
    remove: (id: string) => api.delete<void>(`/api/materials/${id}`),
  },

  parts: {
    create: (materialId: string, data: PartCreate) =>
      api.post<PartOut>(`/api/materials/${materialId}/parts`, {
        json: data,
      }),
    update: (partId: string, data: PartUpdate) =>
      api.patch<PartOut>(`/api/parts/${partId}`, { json: data }),
    remove: (partId: string) => api.delete<void>(`/api/parts/${partId}`),
  },

  questionGroups: {
    create: (partId: string, data: QuestionGroupIn) =>
      api.post<ListeningQuestionGroup>(`/api/parts/${partId}/question-groups`, {
        json: data,
      }),
    update: (groupId: string, data: QuestionGroupIn) =>
      api.patch<ListeningQuestionGroup>(`/api/question-groups/${groupId}`, {
        json: data,
      }),
    remove: (groupId: string) =>
      api.delete<void>(`/api/question-groups/${groupId}`),
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
  },
};
