import { z } from "zod";

const Env = z.object({
  DATABASE_URL: z.url(),
  SESSION_SECRET: z.string().min(32),
  HTTP_PORT: z.coerce.number().int().min(1).max(65535).default(3000),
  FEISHU_APP_ID: z.string().min(1),
  FEISHU_APP_SECRET: z.string().min(1),
  MASTER_KEY: z
    .string()
    .regex(/^[0-9a-f]{64}$/i, "32 random bytes as 64 hex chars (openssl rand -hex 32)"),
  // Only read by the one-time import of the chat Binding (provider-store.ts), which
  // names any that are missing when there is nothing to import from.
  CHAT_PROVIDER_PROTOCOL: z.enum(["openai", "anthropic", "google"]).optional(),
  CHAT_PROVIDER_BASE_URL: z.url().optional(),
  CHAT_PROVIDER_API_KEY: z.string().min(1).optional(),
  CHAT_MODEL: z.string().min(1).optional(),
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
