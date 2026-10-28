import {
  MutationCache,
  QueryCache,
  QueryClient,
  useIsMutating,
  type FetchQueryOptions,
  type QueryKey,
} from "@tanstack/react-query";
import { HTTPError } from "ky";

// Every Admin write shares one key so all forms stay locked until a write and its refresh finish.
export const adminWriteKey = ["admin-write"];

export function useAdminWriting(): boolean {
  return useIsMutating({ mutationKey: adminWriteKey }) > 0;
}

// A read started before the write may return the old state, so cancel it instead of reusing it.
// Never rejects: the query's error state keeps writes disabled until a later reload succeeds.
export async function refreshAfterWrite<TData, TKey extends QueryKey>(
  client: QueryClient,
  options: FetchQueryOptions<TData, Error, TData, TKey>,
): Promise<void> {
  await client.cancelQueries({ queryKey: options.queryKey });
  await client.fetchQuery(options).catch(() => undefined);
}

export function createQueryClient(
  onUnauthorized = () => window.location.replace("/auth/feishu/login"),
) {
  function onError(error: Error) {
    if (error instanceof HTTPError && error.response.status === 401) onUnauthorized();
  }

  return new QueryClient({
    queryCache: new QueryCache({ onError }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: { queries: { retry: false }, mutations: { retry: false, gcTime: 0 } },
  });
}
