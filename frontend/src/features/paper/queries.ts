import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { paperApi, paperEndpoints } from "@/features/paper/api";
import type { AttemptResult, AttemptSubmit } from "@/features/paper/types";

/**
 * The queries addressed by a MATERIAL id rather than by a paper.
 *
 * `/take`, submitting an attempt and reading one back are the same three
 * requests whichever paper the material is — the server does not prefix them
 * by skill for exactly that reason (see `backend/app/api/papers.py`). What
 * still has to be said per paper is which caches a finished attempt disturbs,
 * because those ARE per paper: sitting a reading passage must not invalidate
 * the listening catalogue, and must invalidate the reading one.
 */

/** Every cache key one paper owns, from one place.
 *
 *  Skill-first rather than skill-suffixed (`["reading", "practice"]`, not
 *  `["practice-reading"]`) so that invalidating one paper's whole cache is a
 *  prefix match and never needs listing. */
export function paperKeys(skill: string) {
  return {
    all: [skill] as const,
    take: [skill, "take"] as const,
    practice: [skill, "practice"] as const,
    stats: [skill, "stats"] as const,
    nextUp: [skill, "next-up"] as const,
    collections: [skill, "collections"] as const,
    attempt: [skill, "attempt"] as const,
  };
}

/** The student's render payload — answer-free by construction. Never mix this
 *  query key or cache with the AUTHOR's material query, which carries the
 *  answer key. */
export function useTakeMaterial(skill: string, id: string | undefined) {
  const keys = paperKeys(skill);
  return useQuery({
    queryKey: [...keys.take, id],
    queryFn: () => paperApi.take(id as string),
    enabled: !!id,
  });
}

export function useSubmitAttempt(skill: string, materialId: string) {
  const qc = useQueryClient();
  const keys = paperKeys(skill);
  return useMutation({
    mutationFn: (data: AttemptSubmit) =>
      paperApi.submitAttempt(materialId, data),
    // Finishing a material changes its row in the catalogue — a score where
    // there was none, a better one than last time. Left alone, going back to
    // the list after a test showed it as never attempted.
    //
    // And it moves the panel beside the list, what to practise next, and the
    // bar on every course holding it: progress through a course is counted
    // from attempts, never stored.
    //
    // One invalidation, because every key this paper owns hangs off its own
    // name. The other paper's cache is untouched, which is the whole reason
    // the keys are shaped this way: a reading attempt has nothing to say
    // about the listening catalogue.
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all });
    },
  });
}

/** One finished attempt, by id. A submitted attempt never changes, so this is
 *  fetched once and kept — and `initialData` lets the page that just
 *  submitted hand over the result it already has instead of asking for it
 *  again on the way in. */
export function useAttempt(
  skill: string,
  attemptId: string | undefined,
  seed?: AttemptResult,
) {
  const keys = paperKeys(skill);
  return useQuery({
    queryKey: [...keys.attempt, attemptId],
    queryFn: () => paperApi.attempt(attemptId as string),
    enabled: !!attemptId,
    initialData: seed,
    staleTime: Infinity,
  });
}


// --- The catalogue ---------------------------------------------------------

/** How many rows one fetch brings back. Matches the server's own default;
 *  written down here too because the page needs it to work out the next
 *  offset, and a client guessing at the server's page size is a client that
 *  skips rows the day it changes. */
export const PRACTICE_PAGE = 30;

/**
 * One page of what a learner can sit, filtered and ordered by the server.
 *
 * Takes the paper it is about for the same reason the endpoint is mounted
 * once per skill: it is one query over two libraries, and the only difference
 * is which one.
 */
export function usePracticeCatalogue(
  skill: string,
  params: Record<string, string | string[]>,
) {
  const keys = paperKeys(skill);
  return useInfiniteQuery({
    queryKey: [...keys.practice, params],
    queryFn: ({ pageParam }) =>
      paperEndpoints(skill).practice({
        ...params,
        limit: String(PRACTICE_PAGE),
        offset: String(pageParam),
      }),
    initialPageParam: 0,
    // A chip is a different query key, so without this the list would empty
    // itself to a page of skeletons on every click and fill back in — and the
    // document collapsing under a sticky search field takes the field with
    // it. The old rows stay while the new ones are fetched.
    placeholderData: keepPreviousData,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, page) => n + page.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
    staleTime: 60_000,
  });
}

/** The caller's own figures for one paper. */
export function usePracticeStats(skill: string) {
  const keys = paperKeys(skill);
  return useQuery({
    queryKey: keys.stats,
    queryFn: () => paperEndpoints(skill).practiceStats(),
    staleTime: 60_000,
  });
}

/** What to practise next, and why. */
export function useNextUp(skill: string) {
  const keys = paperKeys(skill);
  return useQuery({
    queryKey: keys.nextUp,
    queryFn: () => paperEndpoints(skill).nextUp(),
    staleTime: 60_000,
  });
}

// --- Drills ------------------------------------------------------------------
//
// Moved here from `features/listening/` with the rest of what both papers
// share. The endpoints were already `paperEndpoints(skill).drills`; only
// these hooks still said listening, and they said it in the cache key, which
// is the one place it would not have shown until a reading drill invalidated
// a listening list.

/** Skill-FIRST, like every other key here: invalidating one paper's drills
 *  must not touch the other's, and a prefix match is what does that. */
export const drillKey = (skill: string) => [skill, "drills"] as const;

/** How many drill cards one fetch brings back. The server's own default,
 *  written down here for the same reason `PRACTICE_PAGE` is. */
export const DRILL_PAGE = 30;

/** The Drills tab's cards — every kind of task, and what there is of it.
 *
 *  Eleven rows counted over the whole library, so it is one fetch and not a
 *  paged one. Held longer than the catalogue: what exists of each type
 *  changes when somebody publishes a material, not while you are reading. */
export function useDrillTypes(
  skill: string,
  params: { part?: number } = {},
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: [...drillKey(skill), "types", params],
    queryFn: () => paperEndpoints(skill).drills.types(params),
    staleTime: 5 * 60_000,
    enabled: options.enabled ?? true,
  });
}

/** One kind of drill, a page at a time. Same shape as the catalogue's
 *  infinite query, and for the same reasons — see `usePracticeCatalogue`. */
export function useDrills(
  skill: string,
  params: { type: string[]; q?: string; part?: number; done?: boolean },
  options: { enabled?: boolean } = {},
) {
  return useInfiniteQuery({
    queryKey: [...drillKey(skill), "list", params],
    queryFn: ({ pageParam }) =>
      paperEndpoints(skill).drills.list({
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
export function useDrillTake(skill: string, groupId: string | undefined) {
  return useQuery({
    queryKey: [...drillKey(skill), "take", groupId],
    queryFn: () => paperEndpoints(skill).drills.take(groupId!),
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
export function useSubmitDrill(skill: string, groupId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: AttemptSubmit) =>
      paperEndpoints(skill).drills.submit(groupId, data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: drillKey(skill) });
    },
  });
}
