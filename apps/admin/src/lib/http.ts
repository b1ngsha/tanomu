import ky, { HTTPError } from "ky";
import { z } from "zod";

// Query owns retries. Writes must never be replayed by the transport.
export const http = ky.create({ baseUrl: window.location.origin, retry: 0, timeout: 15_000 });

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

export function writeErrorMessage(error: unknown): string {
  return needsReconciliation(error)
    ? "请求结果未知，已尝试刷新配置，请确认后再重试。"
    : errorMessage(error);
}

// A definite 4xx rejection is safe to correct; transport/5xx/invalid responses may follow a write.
export function needsReconciliation(error: unknown): boolean {
  return (
    error != null &&
    !(error instanceof HTTPError && error.response.status >= 400 && error.response.status < 500)
  );
}
