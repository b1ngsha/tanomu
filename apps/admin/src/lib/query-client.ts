import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { HTTPError } from "ky";

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
