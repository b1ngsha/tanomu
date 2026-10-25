import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { createChatModelResolver } from "../src/chat-model.ts";
import { createDb, runMigrations, type Db } from "../src/db/client.ts";
import { capabilityBindings, providers } from "../src/db/schema.ts";
import { createKeyCipher } from "../src/key-cipher.ts";
import { importChatBinding } from "../src/provider-store.ts";

const url = process.env.TEST_DATABASE_URL;
const cipher = createKeyCipher("0123456789abcdef".repeat(4));

const env = {
  CHAT_PROVIDER_PROTOCOL: "anthropic",
  CHAT_PROVIDER_BASE_URL: "https://relay.example.com/v1",
  CHAT_PROVIDER_API_KEY: "sk-ant-abcdefghijklmnop",
  CHAT_MODEL: "claude-test",
  CHAT_MODEL_VISION: true,
} as const;

function modelIdOf(model: unknown): string | undefined {
  return typeof model === "object" && model !== null && "modelId" in model
    ? String(model.modelId)
    : undefined;
}

describe.skipIf(!url)("chat model from the stored Binding (Postgres)", () => {
  let db: Db;
  beforeAll(async () => {
    db = createDb(url!);
    await runMigrations(db);
  });
  beforeEach(async () => {
    await db.delete(capabilityBindings);
    await db.delete(providers);
  });
  afterAll(async () => {
    await db.$client.end();
  });

  it("builds the chat model from the Binding as it is at each call", async () => {
    await importChatBinding(db, cipher, env);
    const resolveChatModel = createChatModelResolver(db, cipher);

    const first = await resolveChatModel();
    await db.update(capabilityBindings).set({ model: "claude-other", vision: false });
    const second = await resolveChatModel();

    expect(modelIdOf(first.model)).toBe("claude-test");
    expect(first.vision).toBe(true);
    expect(modelIdOf(second.model)).toBe("claude-other");
    expect(second.vision).toBe(false);
  });

  it("refuses when chat has no Binding", async () => {
    await expect(createChatModelResolver(db, cipher)()).rejects.toThrow(/no Binding/);
  });

  it("refuses a key it can't decrypt instead of falling back", async () => {
    await importChatBinding(db, createKeyCipher("fedcba9876543210".repeat(4)), env);
    await expect(createChatModelResolver(db, cipher)()).rejects.toThrow();
  });
});
