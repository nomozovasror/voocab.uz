import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { listeningApi } from "@/features/listening/api";
import type { AttemptSubmit } from "@/features/paper/types";

const MATERIALS_KEY = ["listening-materials"] as const;

function materialDetailKey(id: string) {
  return [...MATERIALS_KEY, "detail", id] as const;
}

export function useListeningMaterials(scope: "mine" | "public" = "mine") {
  return useQuery({
    queryKey: [...MATERIALS_KEY, scope],
    queryFn: () => listeningApi.materials.list(scope),
  });
}

/** A material's full authoring tree. Both editors read this once, to fill
 *  their own state from, and are the source of truth from then on — which is
 *  why it is fetched fresh every time rather than cached.
 *
 *  The listening editor saves through `listeningApi` directly (its autosave
 *  sends part, group and material writes as one ordered round, which the
 *  mutation hooks below can't express), so nothing it writes ever reaches
 *  this cache. Left cached, the entry kept a snapshot from before those
 *  writes and the next mount hydrated from it — data the editor then held as
 *  current. An author who attached audio, went back to the list and returned
 *  was asked to attach it again, and hydration being one-shot, the refetch
 *  landing a moment later could not correct it.
 *
 *  `gcTime: 0` drops the entry the moment the editor unmounts, so the next
 *  mount has nothing to hydrate from but the server. */
export function useListeningMaterial(id: string | undefined) {
  return useQuery({
    queryKey: materialDetailKey(id ?? ""),
    queryFn: () => listeningApi.materials.get(id as string),
    enabled: !!id,
    gcTime: 0,
    staleTime: 0,
    refetchOnMount: "always",
  });
}

/** Deletes a material and everything under it — parts, questions, and the
 *  attempts anyone has made on it (app/services/materials.py). Irreversible,
 *  so callers ask first.
 *
 *  The studio's own two views are invalidated alongside the materials list:
 *  a deleted material is one fewer row in the listening list and a different
 *  set of counters on the dashboard, and neither is derived from the list
 *  this hook's key covers. */
export function useDeleteListeningMaterial() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => listeningApi.materials.remove(id),
    onSuccess: (_result, id) => {
      qc.removeQueries({ queryKey: materialDetailKey(id) });
      void qc.invalidateQueries({ queryKey: MATERIALS_KEY });
      void qc.invalidateQueries({ queryKey: ["studio-listening"] });
      void qc.invalidateQueries({ queryKey: ["studio-stats"] });
    },
  });
}

// --- Consumption (§8) --------------------------------------------------------

const COLLECTIONS_KEY = ["listening-collections"] as const;

/** How many collections one fetch brings back. Smaller than the catalogue's
 *  page because a collection card is four lines rather than one, and because
 *  there are tens of these where there are thousands of materials. */
export const COLLECTIONS_PAGE = 12;

/**
 * Published collections, a page at a time.
 *
 * Same shape as the catalogue's own infinite query, and for the same reason:
 * the list is browsable, the count is the server's to know, and appending
 * beats a page number. Keyed by the search so a query is its own list rather
 * than a filter applied afterwards.
 */
export function useCollections(
  params: { skill?: string; q?: string; status?: string } = {},
  { enabled = true }: { enabled?: boolean } = {},
) {
  return useInfiniteQuery({
    queryKey: [...COLLECTIONS_KEY, params],
    queryFn: ({ pageParam }) =>
      listeningApi.collections.list({
        ...params,
        limit: COLLECTIONS_PAGE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, page) => n + page.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    // The practice page asks for this only to fill the courses filters and
    // the field's count, both of which are the other mode's business. Left
    // on, every visit to the catalogue fetched a list nobody was looking at.
    enabled,
  });
}

export function useCollection(id: string | undefined) {
  return useQuery({
    queryKey: [...COLLECTIONS_KEY, "detail", id],
    queryFn: () => listeningApi.collections.get(id as string),
    enabled: !!id,
  });
}

/** The author's own. Its own key, because it holds things the learner-facing
 *  list deliberately does not: unpublished collections, and the count of what
 *  is in them that nobody else can see. */
const MY_COLLECTIONS_KEY = ["studio-collections"] as const;

export function useMyCollections() {
  return useQuery({
    queryKey: MY_COLLECTIONS_KEY,
    queryFn: () => listeningApi.collections.mine(),
  });
}

/** Every write to a collection invalidates both listings and the detail.
 *
 *  Both, always: publishing moves a collection from one list into the other,
 *  and a save that only refreshed the one the author is looking at would
 *  leave the learner-facing list holding the version from before. */
function useCollectionWrite<TArgs, TResult>(
  fn: (args: TArgs) => Promise<TResult>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: COLLECTIONS_KEY });
      void qc.invalidateQueries({ queryKey: MY_COLLECTIONS_KEY });
    },
  });
}

export function useCreateCollection() {
  return useCollectionWrite(
    (body: { title: string; summary?: string; skill?: string }) =>
      listeningApi.collections.create(body),
  );
}

export function useUpdateCollection() {
  return useCollectionWrite(
    (args: {
      id: string;
      title?: string;
      summary?: string;
      visibility?: string;
      cover_seed?: string;
    }) => {
      const { id, ...body } = args;
      return listeningApi.collections.update(id, body);
    },
  );
}

export function useSetCollectionItems() {
  return useCollectionWrite((args: { id: string; materialIds: string[] }) =>
    listeningApi.collections.setItems(args.id, args.materialIds),
  );
}

export function useDeleteCollection() {
  return useCollectionWrite((id: string) =>
    listeningApi.collections.remove(id),
  );
}

// --- Editor support -----------------------------------------------------

const PENDING_TRANSCRIPT_STATES = new Set(["pending", "processing"]);

/** Polls while the transcript is pending/processing, stops once it settles
 *  (ready or failed) — the editor's left pane source of segments. */
export function useUpdateSegmentText(assetId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ orderIndex, text }: { orderIndex: number; text: string }) =>
      listeningApi.audioAssets.updateSegment(assetId as string, orderIndex, text),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: ["listening-audio-asset", assetId],
      });
    },
  });
}

export function useAudioAsset(assetId: string | undefined) {
  return useQuery({
    queryKey: ["listening-audio-asset", assetId] as const,
    queryFn: () => listeningApi.audioAssets.get(assetId as string),
    enabled: !!assetId,
    refetchInterval: (query) => {
      const status = query.state.data?.transcript_status;
      return status && PENDING_TRANSCRIPT_STATES.has(status) ? 3000 : false;
    },
  });
}

// --- Drills ------------------------------------------------------------------

export const DRILL_KEY = ["listening-drills"] as const;

/** How many drill cards one fetch brings back. The server's own default,
 *  written down here for the same reason `PRACTICE_PAGE` is. */
export const DRILL_PAGE = 30;

/** The Drills tab's cards — every kind of task, and what there is of it.
 *
 *  Eleven rows counted over the whole library, so it is one fetch and not a
 *  paged one. Held longer than the catalogue: what exists of each type
 *  changes when somebody publishes a material, not while you are reading. */
export function useDrillTypes(
  params: { part?: number } = {},
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: [...DRILL_KEY, "types", params],
    queryFn: () => listeningApi.drills.types(params),
    staleTime: 5 * 60_000,
    enabled: options.enabled ?? true,
  });
}

/** One kind of drill, a page at a time. Same shape as the catalogue's
 *  infinite query, and for the same reasons — see `usePracticeCatalogue`. */
export function useDrills(
  params: { type: string[]; q?: string; part?: number; done?: boolean },
  options: { enabled?: boolean } = {},
) {
  return useInfiniteQuery({
    queryKey: [...DRILL_KEY, "list", params],
    queryFn: ({ pageParam }) =>
      listeningApi.drills.list({
        ...params,
        limit: DRILL_PAGE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    placeholderData: keepPreviousData,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, page) => n + page.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
    staleTime: 60_000,
    enabled: options.enabled ?? true,
  });
}

/** One drill's render payload. Never cached across drills — the key carries
 *  the group — and never `keepPreviousData`: showing the previous drill's
 *  paper while the next one loads would be showing the wrong questions. */
export function useDrillTake(groupId: string | undefined) {
  return useQuery({
    queryKey: [...DRILL_KEY, "take", groupId],
    queryFn: () => listeningApi.drills.take(groupId!),
    enabled: !!groupId,
  });
}

/** Finishing a drill.
 *
 *  It invalidates far less than a sitting does, and that is the point rather
 *  than an oversight: a drill is deliberately invisible to the catalogue, the
 *  recommender, the courses and every ability figure, so refetching them would
 *  be several requests to redraw numbers that cannot have moved. What it does
 *  change is the drill lists and the tab's own counts. */
export function useSubmitDrill(groupId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: AttemptSubmit) =>
      listeningApi.drills.submit(groupId, data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: DRILL_KEY });
    },
  });
}
