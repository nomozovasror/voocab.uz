import { api } from "@/lib/api";
import type {
  Licences,
  ReviewContext,
  ReviewFixPayload,
  ReviewQueue,
  ReviewRow,
} from "@/features/lexicon/types";

export const lexiconApi = {
  reviewQueue: (params: { reason?: string; limit?: number; offset?: number }) =>
    api.get<ReviewQueue>("/api/admin/lexicon/review", { params }),
  reviewContexts: (senseId: string) =>
    api.get<ReviewContext[]>(`/api/admin/lexicon/review/${senseId}/contexts`),
  approve: (senseId: string) =>
    api.post<ReviewRow>(`/api/admin/lexicon/review/${senseId}/approve`),
  fix: (senseId: string, payload: ReviewFixPayload) =>
    api.post<ReviewRow>(`/api/admin/lexicon/review/${senseId}/fix`, {
      json: payload,
    }),
  licences: () => api.get<Licences>("/api/licences"),
};
