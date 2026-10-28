import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { isProviderMissing, needsReconciliation } from "../../lib/http.ts";
import { adminWriteKey, refreshAfterWrite } from "../../lib/query-client.ts";
import { providerQueries } from "../providers/queries.ts";
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
  const refresh = () => refreshAfterWrite(client, chatBindingQueries.get());

  return useMutation({
    mutationKey: adminWriteKey,
    mutationFn: chatBindingApi.save,
    onSuccess: refresh,
    onError: (error) => {
      if (needsReconciliation(error)) return refresh();
      // The selected Provider was deleted elsewhere; drop it from the choices.
      if (isProviderMissing(error)) return refreshAfterWrite(client, providerQueries.list());
      return undefined;
    },
  });
}
