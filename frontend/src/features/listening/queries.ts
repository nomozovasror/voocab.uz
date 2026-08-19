import {
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

export function useSubmitAttempt(materialId: string) {
  return useMutation({
    mutationFn: (data: AttemptSubmit) =>
      listeningApi.submitAttempt(materialId, data),
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
