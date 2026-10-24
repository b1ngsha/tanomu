import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
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

describe.skipIf(!url)("chat Binding import (Postgres)", () => {
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

  it("creates Provider Default and the chat Binding on an empty database", async () => {
    await importChatBinding(db, cipher, env);

    const [provider] = await db.select().from(providers);
    expect(provider).toMatchObject({
      name: "Default",
      protocol: "anthropic",
      baseUrl: "https://relay.example.com/v1",
    });
    expect(provider!.apiKey).not.toContain("abcdefghijklmnop");
    expect(cipher.decrypt(provider!.apiKey)).toBe("sk-ant-abcdefghijklmnop");
    expect(await db.select().from(capabilityBindings)).toMatchObject([
      { capability: "chat", providerId: provider!.id, model: "claude-test", vision: true },
    ]);
  });

  it("ignores env once a chat Binding exists", async () => {
    await importChatBinding(db, cipher, env);
    await importChatBinding(db, cipher, { ...env, CHAT_MODEL: "other-model" });

    expect(await db.select().from(providers)).toHaveLength(1);
    expect(await db.select().from(capabilityBindings)).toMatchObject([{ model: "claude-test" }]);
  });

  it("refuses an incomplete env when there is no chat Binding", async () => {
    const { CHAT_PROVIDER_PROTOCOL, CHAT_PROVIDER_BASE_URL, CHAT_MODEL } = env;
    await expect(
      importChatBinding(db, cipher, { CHAT_PROVIDER_PROTOCOL, CHAT_PROVIDER_BASE_URL, CHAT_MODEL }),
    ).rejects.toThrow(/CHAT_PROVIDER_API_KEY/);
    expect(await db.select().from(providers)).toHaveLength(0);
  });
});
