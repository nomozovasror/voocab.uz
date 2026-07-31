import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { materialsApi } from "@/features/materials/api";
import type {
  MaterialCreate,
  MaterialUpdate,
} from "@/features/materials/types";

const MATERIALS_KEY = ["materials"] as const;

export function useMaterials(scope: "mine" | "public" = "mine") {
  return useQuery({
    queryKey: [...MATERIALS_KEY, scope],
    queryFn: () => materialsApi.list(scope),
  });
}

export function useMaterial(id: string | undefined) {
  return useQuery({
    queryKey: [...MATERIALS_KEY, "detail", id],
    queryFn: () => materialsApi.get(id as string),
    enabled: !!id,
  });
}

export function useCreateMaterial() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: MaterialCreate) => materialsApi.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: MATERIALS_KEY }),
  });
}

export function useUpdateMaterial(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: MaterialUpdate) => materialsApi.update(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: MATERIALS_KEY }),
  });
}

export function useDeleteMaterial() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => materialsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: MATERIALS_KEY }),
  });
}
