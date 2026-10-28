import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { needsReconciliation } from "../../lib/http.ts";
import { adminWriteKey } from "../../lib/query-client.ts";
import { chatBindingApi } from "./api.ts";

export const chatBindingQueries = {
  get: () =>
    queryOptions({
      queryKey: ["capabilities"],
      queryFn: ({ signal }) => chatBindingApi.get(signal),
    }),
};

export function useSaveBinding() {
  const client = useQueryClient();

  async function reconcile() {
    await client.fetchQuery(chatBindingQueries.get()).catch(() => undefined);
  }

  return useMutation({
    mutationKey: adminWriteKey,
    mutationFn: chatBindingApi.save,
    onSuccess: reconcile,
    onError: (error) => (needsReconciliation(error) ? reconcile() : undefined),
  });
}
