import { eq } from "drizzle-orm";
import type { Config } from "./config.ts";
import type { Db } from "./db/client.ts";
import { capabilityBindings, providers } from "./db/schema.ts";
import type { KeyCipher } from "./key-cipher.ts";

type ChatEnv = Partial<
  Pick<
    Config,
    | "CHAT_PROVIDER_PROTOCOL"
    | "CHAT_PROVIDER_BASE_URL"
    | "CHAT_PROVIDER_API_KEY"
    | "CHAT_MODEL"
    | "CHAT_MODEL_VISION"
  >
>;

/**
 * One-time import of the env chat config into the database, run after migrations.
 * Creates Provider `Default` and the chat Binding when no chat Binding exists; otherwise does nothing.
 */
export async function importChatBinding(db: Db, cipher: KeyCipher, env: ChatEnv): Promise<void> {
  await db.transaction(async (tx) => {
    const existing = await tx
      .select({ capability: capabilityBindings.capability })
      .from(capabilityBindings)
      .where(eq(capabilityBindings.capability, "chat"));
    if (existing.length > 0) return;

    const { CHAT_PROVIDER_PROTOCOL, CHAT_PROVIDER_BASE_URL, CHAT_PROVIDER_API_KEY, CHAT_MODEL } =
      env;
    if (
      !CHAT_PROVIDER_PROTOCOL ||
      !CHAT_PROVIDER_BASE_URL ||
      !CHAT_PROVIDER_API_KEY ||
      !CHAT_MODEL
    ) {
      const required = {
        CHAT_PROVIDER_PROTOCOL,
        CHAT_PROVIDER_BASE_URL,
        CHAT_PROVIDER_API_KEY,
        CHAT_MODEL,
      };
      const missing = Object.entries(required)
        .filter(([, value]) => !value)
        .map(([name]) => name);
      throw new Error(`Cannot import the chat Binding, missing ${missing.join(", ")}`);
    }

    const [provider] = await tx
      .insert(providers)
      .values({
        name: "Default",
        protocol: CHAT_PROVIDER_PROTOCOL,
        baseUrl: CHAT_PROVIDER_BASE_URL,
        apiKey: cipher.encrypt(CHAT_PROVIDER_API_KEY),
      })
      .returning({ id: providers.id });
    await tx.insert(capabilityBindings).values({
      capability: "chat",
      providerId: provider!.id,
      model: CHAT_MODEL,
      vision: env.CHAT_MODEL_VISION ?? false,
    });
  });
}
