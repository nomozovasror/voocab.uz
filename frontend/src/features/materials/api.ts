import { apiUrl } from "@/config";
import { ApiError, api } from "@/lib/api";
import type {
  Material,
  MaterialCreate,
  MaterialDetail,
  MaterialUpdate,
} from "@/features/materials/types";

/** Resolve a stored audio URL for playback: absolute (R2) as-is, relative
 *  (local /media/…) against the API origin. */
export function mediaUrl(url: string): string {
  return /^https?:\/\//.test(url) ? url : apiUrl(url);
}

/** Upload an audio clip; returns the stored URL to attach to a material. */
async function uploadAudio(file: File): Promise<string> {
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
  const data = (await res.json()) as { audio_url: string };
  return data.audio_url;
}

export const materialsApi = {
  list: (scope: "mine" | "public" = "mine") =>
    api.get<Material[]>("/api/materials", { params: { scope } }),
  get: (id: string) => api.get<MaterialDetail>(`/api/materials/${id}`),
  create: (data: MaterialCreate) =>
    api.post<MaterialDetail>("/api/materials", { json: data }),
  update: (id: string, data: MaterialUpdate) =>
    api.patch<MaterialDetail>(`/api/materials/${id}`, { json: data }),
  remove: (id: string) => api.delete<void>(`/api/materials/${id}`),
  uploadAudio,
};
