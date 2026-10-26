import {
  MutationCache,
  QueryCache,
  QueryClient,
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { HTTPError } from "ky";
import { z } from "zod";
import { api } from "./api.ts";
import type { ProviderInput } from "./contracts.ts";

export const adminQueries = {
  user: () => queryOptions({ queryKey: ["user"], queryFn: ({ signal }) => api.me(signal) }),
  providers: () =>
    queryOptions({ queryKey: ["providers"], queryFn: ({ signal }) => api.providers(signal) }),
  capabilities: () =>
    queryOptions({ queryKey: ["capabilities"], queryFn: ({ signal }) => api.capabilities(signal) }),
};

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

const errorBody = z.object({
  error: z.enum([
    "duplicate-provider-name",
    "provider-in-use",
    "provider-not-found",
    "invalid-request",
  ]),
});
const messages = {
  "duplicate-provider-name": "Provider 名称已存在，请更换名称。",
  "provider-in-use": "Provider 正在被使用，请先修改 Binding。",
  "provider-not-found": "Provider 不存在，请刷新配置。",
  "invalid-request": "请求内容无效，请检查输入。",
};
export function errorMessage(error: unknown): string {
  if (error instanceof HTTPError) {
    if (error.response.status === 401) return "登录已过期，请重新登录。";
    const parsed = errorBody.safeParse(error.data);
    if (parsed.success) return messages[parsed.data.error];
  }
  return "请求失败，请重试或刷新配置。";
}

// A definite 4xx rejection is safe to correct; transport/5xx/invalid responses may follow a write.
export function needsReconciliation(error: unknown): boolean {
  return (
    error != null &&
    !(error instanceof HTTPError && error.response.status >= 400 && error.response.status < 500)
  );
}

export function useSaveProvider() {
  const client = useQueryClient();
  return useMutation({
    mutationKey: ["admin-write"],
    mutationFn: ({ id, input }: { id: string | null; input: ProviderInput }) =>
      api.saveProvider(id, input),
    onSuccess: () => client.invalidateQueries({ queryKey: adminQueries.providers().queryKey }),
  });
}
export function useDeleteProvider() {
  const client = useQueryClient();
  return useMutation({
    mutationKey: ["admin-write"],
    mutationFn: api.removeProvider,
    onSuccess: () => client.invalidateQueries({ queryKey: adminQueries.providers().queryKey }),
  });
}
export function useSaveBinding() {
  const client = useQueryClient();
  return useMutation({
    mutationKey: ["admin-write"],
    mutationFn: api.saveBinding,
    onSuccess: () => client.invalidateQueries({ queryKey: adminQueries.capabilities().queryKey }),
  });
}
