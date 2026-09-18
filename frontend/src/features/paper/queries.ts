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
