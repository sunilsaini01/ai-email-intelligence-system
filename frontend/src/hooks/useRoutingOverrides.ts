import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { routingOverridesApi } from "../api/routingOverrides";
import type { RoutingOverrideCreateRequest } from "../types/routingOverrides";

export function useRoutingOverrides() {
  return useQuery({
    queryKey: ["routing-overrides"],
    queryFn: () => routingOverridesApi.list(),
  });
}

export function useRoutingOverrideMutations() {
  const queryClient = useQueryClient();
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ["routing-overrides"] });

  const create = useMutation({
    mutationFn: (request: RoutingOverrideCreateRequest) => routingOverridesApi.create(request),
    onSuccess: invalidate,
  });

  const toggleActive = useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      routingOverridesApi.update(id, { is_active: isActive }),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (id: string) => routingOverridesApi.remove(id),
    onSuccess: invalidate,
  });

  return { create, toggleActive, remove };
}
