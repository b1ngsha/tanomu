import { QueryClient, queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { needsReconciliation } from "../../lib/http.ts";
import { providerApi } from "./api.ts";
import type { ProviderInput } from "./contracts.ts";

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

export function useSaveProvider() {
  const client = useQueryClient();
  return useMutation({
    mutationKey: ["admin-write"],
    mutationFn: ({ id, input }: { id: string | null; input: ProviderInput }) =>
      providerApi.save(id, input),
    onSuccess: () => reconcile(client),
    onError: (error) => (needsReconciliation(error) ? reconcile(client) : undefined),
  });
}

export function useDeleteProvider() {
  const client = useQueryClient();
  return useMutation({
    mutationKey: ["admin-write"],
    mutationFn: providerApi.remove,
    onSuccess: () => reconcile(client),
    onError: (error) => (needsReconciliation(error) ? reconcile(client) : undefined),
  });
}
