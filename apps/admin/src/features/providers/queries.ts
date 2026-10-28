import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { isProviderMissing, needsReconciliation } from "../../lib/http.ts";
import { adminWriteKey, refreshAfterWrite } from "../../lib/query-client.ts";
import { providerApi } from "./api.ts";
import type { ProviderPatch } from "./contracts.ts";

export const providerQueries = {
  list: () =>
    queryOptions({
      queryKey: ["providers"],
      queryFn: ({ signal }) => providerApi.list(signal),
    }),
};

function useProviderWrite<TData, TVariables>(
  mutationFn: (variables: TVariables) => Promise<TData>,
) {
  const client = useQueryClient();
  const refresh = () => refreshAfterWrite(client, providerQueries.list());

  return useMutation({
    mutationKey: adminWriteKey,
    mutationFn,
    onSuccess: refresh,
    onError: (error) =>
      needsReconciliation(error) || isProviderMissing(error) ? refresh() : undefined,
  });
}

export function useCreateProvider() {
  return useProviderWrite(providerApi.create);
}

export function useUpdateProvider() {
  return useProviderWrite(({ id, patch }: { id: string; patch: ProviderPatch }) =>
    providerApi.update(id, patch),
  );
}

export function useDeleteProvider() {
  return useProviderWrite(providerApi.remove);
}
