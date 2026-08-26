import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { listeningApi } from "@/features/listening/api";
import type { AttemptResult, AttemptSubmit } from "@/features/listening/types";

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

const TAKE_KEY = ["listening-take"] as const;

/** The student's render payload — answer-free by construction. Never mix
 *  this query key/cache with the author `useListeningMaterial` above. */
export function useTakeMaterial(id: string | undefined) {
  return useQuery({
    queryKey: [...TAKE_KEY, id],
    queryFn: () => listeningApi.take(id as string),
    enabled: !!id,
  });
}

const PRACTICE_KEY = ["listening-practice"] as const;

/** How many rows one fetch brings back. Matches the server's own default;
 *  written down here too because the page needs it to work out the next
 *  offset, and a client guessing at the server's page size is a client that
 *  skips rows the day it changes. */
export const PRACTICE_PAGE = 30;

/**
 * The catalogue, a page at a time.
 *
 * `useInfiniteQuery` rather than `useQuery` because the list is now paged and
 * the page scrolls: each fetch appends, and the whole thing is one cache
 * entry keyed by the filters. Change a chip and that is a different key — a
 * different list, from the top, which is right: a filter is not a scroll
 * position.
 *
 * `getNextPageParam` returns undefined when the pages in hand already cover
 * the total, which is what turns the sentinel at the bottom of the list off.
 * It counts what arrived rather than trusting `offset + PAGE` to be right:
 * the server clamps `limit`, and a client that assumed otherwise would ask
 * for a page that starts past where it actually got to and skip rows.
 */
export function usePracticeCatalogue(
  params: Record<string, string | string[]>,
) {
  return useInfiniteQuery({
    queryKey: [...PRACTICE_KEY, params],
    queryFn: ({ pageParam }) =>
      listeningApi.practice({
        ...params,
        limit: String(PRACTICE_PAGE),
        offset: String(pageParam),
      }),
    initialPageParam: 0,
    // A chip is a different query key, so without this the list would empty
    // itself to a page of skeletons on every click and fill back in — and
    // the document collapsing under a sticky search field takes the field
    // with it. The old rows stay while the new ones are fetched, and
    // `isPlaceholderData` is what says they are the old ones.
    placeholderData: keepPreviousData,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, page) => n + page.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
    // The rows are a moving target — somebody else's material is published,
    // the difficulty refresh lands — and refetching every page on every
    // window focus would be several requests to redraw a list nobody asked
    // to be redrawn. A minute is long enough to cover a trip to the tab
    // beside this one.
    staleTime: 60_000,
  });
}

const PRACTICE_STATS_KEY = ["listening-practice-stats"] as const;

/** What the learner is good and bad at — the catalogue's right-hand panel.
 *
 *  Its own query rather than a field on the catalogue: the two answer
 *  different questions ("what is there to sit" and "where am I weak"), the
 *  panel is a third of the page and the list is the rest of it, and a single
 *  response would make the list wait on an aggregate over every answer the
 *  learner has ever given. Invalidated by the same submit, because finishing
 *  something moves both. */
export function usePracticeStats() {
  return useQuery({
    queryKey: PRACTICE_STATS_KEY,
    queryFn: () => listeningApi.practiceStats(),
  });
}

export function useSubmitAttempt(materialId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: AttemptSubmit) =>
      listeningApi.submitAttempt(materialId, data),
    // Finishing a material changes its row in the catalogue — a score where
    // there was none, a better one than last time. Left alone, going back to
    // the list after a test showed it as never attempted.
    //
    // And it moves the panel beside the list: a part's accuracy, the weakest
    // one, the totals underneath. The very first submit changes it from
    // "start with Part 1" into a panel with numbers in it.
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: PRACTICE_KEY });
      void qc.invalidateQueries({ queryKey: PRACTICE_STATS_KEY });
    },
  });
}

/** One finished attempt, by id. A submitted attempt never changes, so this is
 *  fetched once and kept — and `initialData` lets the page that just
 *  submitted hand over the result it already has instead of asking for it
 *  again on the way in. */
export function useAttempt(attemptId: string | undefined, seed?: AttemptResult) {
  return useQuery({
    queryKey: ["listening-attempt", attemptId],
    queryFn: () => listeningApi.attempt(attemptId as string),
    enabled: !!attemptId,
    initialData: seed,
    staleTime: Infinity,
  });
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
