import { MutationCache, QueryCache, QueryClient, useIsMutating } from "@tanstack/react-query";
import { HTTPError } from "ky";

// Every Admin write shares one key so all forms stay locked until a write and its refresh finish.
export const adminWriteKey = ["admin-write"];

export function useAdminWriting(): boolean {
  return useIsMutating({ mutationKey: adminWriteKey }) > 0;
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
