import { QueryClient, queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { needsReconciliation } from "../../lib/http.ts";
import { adminWriteKey } from "../../lib/query-client.ts";
import { providerApi } from "./api.ts";
import type { ProviderPatch } from "./contracts.ts";

export const providerQueries = {
  list: () =>
    queryOptions({
      queryKey: ["providers"],
      queryFn: ({ signal }) => providerApi.list(signal),
    }),
};

async function reconcile(client: QueryClient) {
  // Mutation callbacks must not reject. The query's error state disables writes until a later reload succeeds.
  await client.fetchQuery(providerQueries.list()).catch(() => undefined);
}

function useProviderWrite<TData, TVariables>(
  mutationFn: (variables: TVariables) => Promise<TData>,
) {
  const client = useQueryClient();

  return useMutation({
    mutationKey: adminWriteKey,
    mutationFn,
    onSuccess: () => reconcile(client),
    onError: (error) => (needsReconciliation(error) ? reconcile(client) : undefined),
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
