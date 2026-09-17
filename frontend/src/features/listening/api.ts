import { apiUrl } from "@/config";
import { ApiError, api } from "@/lib/api";
import type { RequestOptions } from "@/lib/api";
import type {
  AudioSegment,
  AttemptResult,
  AttemptSubmit,
  AudioAssetDetail,
  AudioUpload,
  ImageUpload,
  ListeningMaterial,
  ListeningMaterialCreate,
  ListeningMaterialDetail,
  ListeningMaterialUpdate,
  ListeningQuestionGroup,
  ListeningStats,
  MaterialTake,
  PartCreate,
  PartOut,
  PartUpdate,
  AuthorCollection,
  CollectionDetail,
  CollectionList,
  DrillList,
  DrillTake,
  DrillType,
  NextUp,
  PracticeCatalogue,
  QuestionGroupIn,
} from "@/features/listening/types";

/** Resolve a stored audio URL for playback: absolute (R2) as-is, relative
 *  (local /media/…) against the API origin. */
export function mediaUrl(url: string): string {
  return /^https?:\/\//.test(url) ? url : apiUrl(url);
}

/** POST one file as multipart, and read the failure back in the server's own
 *  words. Not `api.post`: that sends JSON, and the browser has to be left to
 *  set the multipart Content-Type itself so it can put the boundary in. */
async function uploadFile<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  let res: Response;
  try {
    res = await fetch(apiUrl(path), {
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
  return (await res.json()) as T;
}

/** Upload an audio clip; returns the asset to attach to a material. */
const uploadAudio = (file: File) =>
  uploadFile<AudioUpload>("/api/uploads/audio", file);

/** Upload a picture for a map or diagram task. What comes back is the id to
 *  store on the group, plus what it takes to draw it straight away — the
 *  format was decided by the file's own header, not by its name, so what was
 *  accepted may not be what the extension claimed. */
const uploadImage = (file: File) =>
  uploadFile<ImageUpload>("/api/uploads/image", file);

export const listeningApi = {
  uploadAudio,
  uploadImage,

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
  /** One page of what a learner can sit, with their own history against each
   *  one. Not `materials.list` — that is the author's view and carries
   *  drafts.
   *
   *  Filters, order and paging are all the server's: at a thousand materials
   *  sending the library so the browser can hide most of it is half a
   *  megabyte of JSON to show thirty titles. `params` is whatever
   *  `catalogueParams` made of the controls, plus the page bounds.
   *
   *  An array value becomes a repeated parameter (`types=a&types=b`), which
   *  is what FastAPI reads a `list[str]` query from — a comma-joined string
   *  would arrive as one type nobody has. */
  practice: (params: Record<string, string | string[]> = {}) => {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      for (const one of Array.isArray(value) ? value : [value]) {
        search.append(key, one);
      }
    }
    const query = search.toString();
    return api.get<PracticeCatalogue>(
      `/api/listening/practice${query ? `?${query}` : ""}`,
    );
  },

  /** Drills: one question group practised on its own.
   *
   *  A separate corner of the API from `practice`, because it lists a
   *  different thing. The catalogue lists materials; this lists groups cut
   *  out of them, which is what somebody who wants to work only on maps is
   *  actually after. */
  drills: {
    /** The tab's cards: every kind of task, and what there is of it. */
    types: (params: { part?: number } = {}) =>
      api.get<{ items: DrillType[] }>("/api/listening/drills/types", {
        params,
      }),
    list: (
      params: {
        type: string;
        q?: string;
        part?: number;
        done?: boolean;
        limit?: number;
        offset?: number;
      },
    ) => api.get<DrillList>("/api/listening/drills", { params }),
    take: (groupId: string) =>
      api.get<DrillTake>(`/api/listening/drills/${groupId}`),
    submit: (groupId: string, body: AttemptSubmit) =>
      api.post<AttemptResult>(`/api/listening/drills/${groupId}/attempts`, {
        json: body,
      }),
  },

  collections: {
    /** Published collections with the caller's progress through each.
     *
     *  Ordered by that progress rather than by date — in progress, then
     *  untouched, then finished — because what somebody wants from a list of
     *  courses is the one they were in the middle of. */
    list: (
      params: {
        q?: string;
        status?: string;
        limit?: number;
        offset?: number;
      } = {},
    ) =>
      api.get<CollectionList>("/api/collections", { params }),
    get: (id: string) => api.get<CollectionDetail>(`/api/collections/${id}`),
    /** The caller's own, published or not. */
    mine: () => api.get<AuthorCollection[]>("/api/studio/collections"),
    create: (body: { title: string; summary?: string }) =>
      api.post<AuthorCollection>("/api/collections", { json: body }),
    update: (
      id: string,
      body: {
        title?: string;
        summary?: string;
        visibility?: string;
        /** A new string to generate the cover from. Hex, 4–32 characters —
         *  the server validates the shape, because nothing reads this
         *  except the hash and a free-text field nobody displays is
         *  somewhere text ends up. */
        cover_seed?: string;
      },
    ) => api.patch<AuthorCollection>(`/api/collections/${id}`, { json: body }),
    /** The whole ordered list, every time — see the endpoint's own note on
     *  why there is no add/remove/move. */
    setItems: (id: string, materialIds: string[]) =>
      api.put<AuthorCollection>(`/api/collections/${id}/items`, {
        json: { material_ids: materialIds },
      }),
    remove: (id: string) => api.delete<void>(`/api/collections/${id}`),
  },

  /** A few materials to practise next, and why those. Its own request rather
   *  than a field on the catalogue: that answers "what is there", this
   *  answers "what should I do", and changing a filter is not asking the
   *  second question again. */
  nextUp: () => api.get<NextUp>("/api/listening/next"),

  /** The caller's own listening statistics — the practice page's right-hand
   *  panel. There is no user id in the path and no way to ask for anybody
   *  else's: a record of what a person keeps getting wrong is theirs. */
  practiceStats: () => api.get<ListeningStats>("/api/listening/stats"),

  take: (materialId: string) =>
    api.get<MaterialTake>(`/api/materials/${materialId}/take`),

  submitAttempt: (materialId: string, data: AttemptSubmit) =>
    api.post<AttemptResult>(`/api/materials/${materialId}/attempts`, {
      json: data,
    }),

  /** One of the caller's own attempts, in full. What makes it necessary is
   *  the refresh key: a result that only lives in the response to the submit
   *  is a result a reload throws away. Someone else's attempt is a 404, the
   *  material's author included. */
  attempt: (attemptId: string) =>
    api.get<AttemptResult>(`/api/attempts/${attemptId}`),

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
