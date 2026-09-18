import { apiUrl } from "@/config";
import { ApiError, api } from "@/lib/api";
import type { RequestOptions } from "@/lib/api";
import type {
  AttemptResult,
  AttemptSubmit,
  AudioUpload,
  ImageUpload,
  PaperMaterial,
  PaperMaterialCreate,
  PaperMaterialDetail,
  PaperMaterialUpdate,
  PaperQuestionGroup,
  LearnerStats,
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
} from "@/features/paper/types";

/**
 * What both papers call, and the factory for what only one of them does.
 *
 * The split is the client's copy of the server's: everything addressed by a
 * MATERIAL id — the authoring tree, `/take`, an attempt — is one set of
 * endpoints whichever paper the material is, because a caller holding an id
 * does not know which. Everything addressed by SKILL — the catalogue, the
 * recommendation, the statistics, the drills — is `paperEndpoints(skill)`,
 * mounted twice, so a filter added to one reaches both and there is no second
 * copy to forget.
 *
 * See `backend/app/api/papers.py`, which is the same decision on the other
 * side of the wire.
 */

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

export const paperApi = {
  uploadAudio,
  uploadImage,

  materials: {
    list: (scope: "mine" | "public" = "mine") =>
      api.get<PaperMaterial[]>("/api/materials", { params: { scope } }),
    get: (id: string) => api.get<PaperMaterialDetail>(`/api/materials/${id}`),
    create: (data: PaperMaterialCreate) =>
      api.post<PaperMaterialDetail>("/api/materials", { json: data }),
    update: (
      id: string,
      data: PaperMaterialUpdate,
      opts?: RequestOptions,
    ) =>
      api.patch<PaperMaterialDetail>(`/api/materials/${id}`, {
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
      api.post<PaperQuestionGroup>(`/api/parts/${partId}/question-groups`, {
        ...opts,
        json: data,
      }),
    update: (groupId: string, data: QuestionGroupIn, opts?: RequestOptions) =>
      api.patch<PaperQuestionGroup>(`/api/question-groups/${groupId}`, {
        ...opts,
        json: data,
      }),
    remove: (groupId: string, opts?: RequestOptions) =>
      api.delete<void>(`/api/question-groups/${groupId}`, opts),
    /** The part's groups in their new order — all of them, by id. A move is
     *  sent as the whole order rather than as a direction, so two windows
     *  can't interleave two half-moves into an order neither asked for. */
    reorder: (partId: string, groupIds: string[], opts?: RequestOptions) =>
      api.put<PaperQuestionGroup[]>(
        `/api/parts/${partId}/question-groups/order`,
        { ...opts, json: { group_ids: groupIds } },
      ),
  },

  // --- Consumption (§8): the ONLY read path the take/practice UI may use.
  // Never call materials.get() (the author endpoint) from consumption code —
  // it carries correct_answers. `take` is structurally guaranteed answer-free
  // (backend's TakeQuestionOut has no such field at all).
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

};


/**
 * The half of the API that is about ONE paper.
 *
 * A factory rather than two objects, for the reason the server's router is a
 * factory: these differ only in a path segment, and two hand-written copies
 * are identical on the day they are written and drift from the first fix
 * applied to one of them.
 */
export function paperEndpoints(skill: string) {
  return {
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
        `/api/${skill}/practice${query ? `?${query}` : ""}`,
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
        api.get<{ items: DrillType[] }>(`/api/${skill}/drills/types`, {
          params,
        }),
      /** One page of one card's exercises.
       *
       *  The query is built by hand rather than handed to the `params` helper,
       *  for the reason `practice` does the same: `type` REPEATS — a card can
       *  cover two kinds of question — and that is what FastAPI reads a
       *  `list[str]` from. Comma-joined it would arrive as one type nobody
       *  has. */
      list: (params: {
        type: string[];
        q?: string;
        part?: number;
        done?: boolean;
        limit?: number;
        offset?: number;
      }) => {
        const search = new URLSearchParams();
        for (const type of params.type) search.append("type", type);
        if (params.q) search.set("q", params.q);
        if (params.part != null) search.set("part", String(params.part));
        if (params.done) search.set("done", "true");
        if (params.limit != null) search.set("limit", String(params.limit));
        if (params.offset != null) search.set("offset", String(params.offset));
        return api.get<DrillList>(`/api/${skill}/drills?${search}`);
      },
      take: (groupId: string) =>
        api.get<DrillTake>(`/api/${skill}/drills/${groupId}`),
      submit: (groupId: string, body: AttemptSubmit) =>
        api.post<AttemptResult>(`/api/${skill}/drills/${groupId}/attempts`, {
          json: body,
        }),
    },

    /** A few materials to practise next, and why those. Its own request rather
     *  than a field on the catalogue: that answers "what is there", this
     *  answers "what should I do", and changing a filter is not asking the
     *  second question again. */
    nextUp: () => api.get<NextUp>(`/api/${skill}/next`),

    /** The caller's own statistics for this paper — the practice page's right-hand
     *  panel. There is no user id in the path and no way to ask for anybody
     *  else's: a record of what a person keeps getting wrong is theirs. */
    practiceStats: () => api.get<LearnerStats>(`/api/${skill}/stats`),
  };
}
