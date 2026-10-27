import { z } from "zod";

export const providerProtocol = z.enum(["openai", "anthropic", "google"]);
const nonempty = z.string().trim().min(1, "不能为空");
export const providerFields = z.object({
  name: nonempty,
  protocol: providerProtocol,
  baseUrl: z.url({ protocol: /^https?$/, error: "请输入 HTTP(S) 地址" }),
  apiKey: z.string().refine((value) => value === "" || value.trim().length > 0, "密钥不能只有空格"),
});
export const providerCreate = providerFields.extend({
  apiKey: providerFields.shape.apiKey.refine((value) => value.length > 0, "请输入 API Key"),
});
export const providerView = providerFields.omit({ apiKey: true }).extend({
  id: z.uuid(),
  apiKeyMask: z.string().min(1),
});
export const chatBinding = z.object({
  providerId: z.uuid({ error: "请选择 Provider" }),
  model: nonempty,
  vision: z.boolean(),
});
export const userView = z.object({ openId: z.string().min(1), name: z.string().min(1) });
export type Provider = z.infer<typeof providerView>;
export type ProviderInput = z.infer<typeof providerFields>;
export type Binding = z.infer<typeof chatBinding>;
