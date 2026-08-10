import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { listeningApi } from "@/features/listening/api";
import type {
  AttemptSubmit,
  ListeningMaterialCreate,
  ListeningMaterialUpdate,
  PartCreate,
  QuestionGroupIn,
} from "@/features/listening/types";

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

export function useListeningMaterial(id: string | undefined) {
  return useQuery({
    queryKey: materialDetailKey(id ?? ""),
    queryFn: () => listeningApi.materials.get(id as string),
    enabled: !!id,
  });
}

export function useCreateListeningMaterial() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ListeningMaterialCreate) =>
      listeningApi.materials.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: MATERIALS_KEY }),
  });
}

export function useUpdateListeningMaterial(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ListeningMaterialUpdate) =>
      listeningApi.materials.update(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: MATERIALS_KEY });
    },
  });
}

export function useDeleteListeningMaterial() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => listeningApi.materials.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: MATERIALS_KEY }),
  });
}

export function useCreatePart(materialId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: PartCreate) =>
      listeningApi.parts.create(materialId, data),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: materialDetailKey(materialId) }),
  });
}

export function useDeletePart(materialId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (partId: string) => listeningApi.parts.remove(partId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: materialDetailKey(materialId) }),
  });
}

export function useCreateQuestionGroup(materialId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ partId, data }: { partId: string; data: QuestionGroupIn }) =>
      listeningApi.questionGroups.create(partId, data),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: materialDetailKey(materialId) }),
  });
}

export function useUpdateQuestionGroup(materialId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      groupId,
      data,
    }: {
      groupId: string;
      data: QuestionGroupIn;
    }) => listeningApi.questionGroups.update(groupId, data),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: materialDetailKey(materialId) }),
  });
}

export function useDeleteQuestionGroup(materialId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (groupId: string) => listeningApi.questionGroups.remove(groupId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: materialDetailKey(materialId) }),
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

// --- Editor support -----------------------------------------------------

const PENDING_TRANSCRIPT_STATES = new Set(["pending", "processing"]);

/** Polls while the transcript is pending/processing, stops once it settles
 *  (ready or failed) — the editor's left pane source of segments. */
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
