import { eq, sql } from "drizzle-orm";
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

export type ProviderProtocol = (typeof providers.$inferSelect)["protocol"];

export interface ProviderView {
  id: string;
  name: string;
  protocol: ProviderProtocol;
  baseUrl: string;
  apiKeyMask: string;
}

export interface CreateProviderInput {
  name: string;
  protocol: ProviderProtocol;
  baseUrl: string;
  apiKey: string;
}

export interface UpdateProviderInput {
  name?: string;
  protocol?: ProviderProtocol;
  baseUrl?: string;
  apiKey?: string;
}

export type ProviderStoreErrorCode =
  | "provider-not-found"
  | "duplicate-provider-name"
  | "provider-in-use";

export class ProviderStoreError extends Error {
  readonly code: ProviderStoreErrorCode;

  constructor(code: ProviderStoreErrorCode) {
    super(code);
    this.code = code;
  }
}

export interface ChatBinding {
  providerId: string;
  model: string;
  vision: boolean;
}

export interface ProviderStore {
  getChatBinding(): Promise<ChatBinding | null>;
  putChatBinding(input: ChatBinding): Promise<ChatBinding>;
  listProviders(): Promise<ProviderView[]>;
  createProvider(input: CreateProviderInput): Promise<ProviderView>;
  updateProvider(id: string, input: UpdateProviderInput): Promise<ProviderView>;
  deleteProvider(id: string): Promise<void>;
}

function databaseErrorCode(error: unknown): string | undefined {
  if (!(error instanceof Error)) return undefined;
  if ("code" in error && typeof error.code === "string") return error.code;
  if ("cause" in error) {
    const cause = error.cause;
    if (cause && typeof cause === "object" && "code" in cause && typeof cause.code === "string") {
      return cause.code;
    }
  }
  return undefined;
}

function providerView(provider: typeof providers.$inferSelect, cipher: KeyCipher): ProviderView {
  return {
    id: provider.id,
    name: provider.name,
    protocol: provider.protocol,
    baseUrl: provider.baseUrl,
    apiKeyMask: cipher.mask(provider.apiKey),
  };
}

/**
 * One-time import of the env chat config into the database, run after migrations.
 * Creates Provider `Default` and the chat Binding when no chat Binding exists; otherwise does nothing.
 */
export async function importChatBinding(db: Db, cipher: KeyCipher, env: ChatEnv): Promise<void> {
  await db.transaction(async (tx) => {
    // Instances starting together wait here; each later one then sees the committed Binding.
    await tx.execute(sql`select pg_advisory_xact_lock(hashtext('import_chat_binding'))`);
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

export function createProviderStore(db: Db, cipher: KeyCipher): ProviderStore {
  return {
    async getChatBinding() {
      const [binding] = await db
        .select({
          providerId: capabilityBindings.providerId,
          model: capabilityBindings.model,
          vision: capabilityBindings.vision,
        })
        .from(capabilityBindings)
        .where(eq(capabilityBindings.capability, "chat"));
      return binding ?? null;
    },

    async putChatBinding(input) {
      return db.transaction(async (tx) => {
        const [provider] = await tx
          .select({ id: providers.id })
          .from(providers)
          .where(eq(providers.id, input.providerId))
          .for("key share");
        if (!provider) throw new ProviderStoreError("provider-not-found");
        const [binding] = await tx
          .insert(capabilityBindings)
          .values({
            capability: "chat",
            ...input,
          })
          .onConflictDoUpdate({
            target: capabilityBindings.capability,
            set: { ...input, updatedAt: new Date() },
          })
          .returning({
            providerId: capabilityBindings.providerId,
            model: capabilityBindings.model,
            vision: capabilityBindings.vision,
          });
        return binding!;
      });
    },

    async listProviders() {
      const rows = await db.select().from(providers);
      return rows.map((provider) => providerView(provider, cipher));
    },

    async createProvider(input) {
      try {
        const [provider] = await db
          .insert(providers)
          .values({
            name: input.name,
            protocol: input.protocol,
            baseUrl: input.baseUrl,
            apiKey: cipher.encrypt(input.apiKey),
          })
          .returning();
        return providerView(provider!, cipher);
      } catch (error) {
        if (databaseErrorCode(error) === "23505") {
          throw new ProviderStoreError("duplicate-provider-name");
        }
        throw error;
      }
    },

    async updateProvider(id, input) {
      const values: Partial<typeof providers.$inferInsert> = {
        updatedAt: new Date(),
      };
      if (input.name !== undefined) values.name = input.name;
      if (input.protocol !== undefined) values.protocol = input.protocol;
      if (input.baseUrl !== undefined) values.baseUrl = input.baseUrl;
      if (input.apiKey) values.apiKey = cipher.encrypt(input.apiKey);

      try {
        const [provider] = await db
          .update(providers)
          .set(values)
          .where(eq(providers.id, id))
          .returning();
        if (!provider) throw new ProviderStoreError("provider-not-found");
        return providerView(provider, cipher);
      } catch (error) {
        if (error instanceof ProviderStoreError) throw error;
        if (databaseErrorCode(error) === "23505") {
          throw new ProviderStoreError("duplicate-provider-name");
        }
        throw error;
      }
    },

    async deleteProvider(id) {
      try {
        const deleted = await db
          .delete(providers)
          .where(eq(providers.id, id))
          .returning({ id: providers.id });
        if (deleted.length === 0) throw new ProviderStoreError("provider-not-found");
      } catch (error) {
        if (error instanceof ProviderStoreError) throw error;
        if (databaseErrorCode(error) === "23001") {
          throw new ProviderStoreError("provider-in-use");
        }
        throw error;
      }
    },
  };
}
