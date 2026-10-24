import { z } from "zod";

const Env = z.object({
  DATABASE_URL: z.url(),
  SESSION_SECRET: z.string().min(32),
  HTTP_PORT: z.coerce.number().int().min(1).max(65535).default(3000),
  FEISHU_APP_ID: z.string().min(1),
  FEISHU_APP_SECRET: z.string().min(1),
  CHAT_PROVIDER_PROTOCOL: z.enum(["openai", "anthropic", "google"]),
  CHAT_PROVIDER_BASE_URL: z.url(),
  CHAT_PROVIDER_API_KEY: z.string().min(1),
  CHAT_MODEL: z.string().min(1),
  CHAT_MODEL_VISION: z.stringbool().default(false),
});

export type Config = z.infer<typeof Env>;

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const parsed = Env.safeParse(env);
  if (!parsed.success) {
    throw new Error(`Invalid environment, see .env.example:\n${z.prettifyError(parsed.error)}`);
  }
  return parsed.data;
}
