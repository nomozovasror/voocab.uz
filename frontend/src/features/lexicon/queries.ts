import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { lexiconApi } from "@/features/lexicon/api";
import type { ReviewFixPayload } from "@/features/lexicon/types";

const REVIEW_QUEUE_KEY = "lexicon-review" as const;

export function useReviewQueue(reason: string | null, limit = 50) {
  return useQuery({
    queryKey: [REVIEW_QUEUE_KEY, reason, limit] as const,
    queryFn: () => lexiconApi.reviewQueue({ reason: reason ?? undefined, limit }),
  });
}

/** Whether Studio should offer the review tab at all — a cheap `limit: 1`
 *  call for its count, made only once the caller already knows the user is
 *  an admin (see `StudioTabsHeader`). */
export function useReviewQueueCount(enabled: boolean) {
  return useQuery({
    queryKey: [REVIEW_QUEUE_KEY, "count"] as const,
    queryFn: () => lexiconApi.reviewQueue({ limit: 1 }),
    enabled,
    select: (data) => data.total,
  });
}

export function useReviewContexts(senseId: string | null) {
  return useQuery({
    queryKey: ["lexicon-review-contexts", senseId] as const,
    queryFn: () => lexiconApi.reviewContexts(senseId as string),
    enabled: senseId != null,
  });
}

export function useApproveSense() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (senseId: string) => lexiconApi.approve(senseId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [REVIEW_QUEUE_KEY] });
    },
  });
}

export function useFixSense() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      senseId,
      payload,
    }: {
      senseId: string;
      payload: ReviewFixPayload;
    }) => lexiconApi.fix(senseId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [REVIEW_QUEUE_KEY] });
    },
  });
}

export function useLicences() {
  return useQuery({
    queryKey: ["licences"] as const,
    queryFn: lexiconApi.licences,
  });
}
