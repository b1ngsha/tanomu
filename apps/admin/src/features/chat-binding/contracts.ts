import { z } from "zod";

export const chatBinding = z.object({
  providerId: z.uuid({ error: "请选择 Provider" }),
  model: z.string().trim().min(1, "不能为空"),
  vision: z.boolean(),
});
export type Binding = z.infer<typeof chatBinding>;
