import { randomUUID } from "node:crypto";
import type { IncomingMessage } from "@tanomu/core";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createConversationStore } from "../src/conversation-store.ts";
import { createDb, runMigrations, type Db } from "../src/db/client.ts";

const url = process.env.TEST_DATABASE_URL;

function incoming(): IncomingMessage {
  return {
    id: `om_${randomUUID()}`,
    chatId: `oc_${randomUUID()}`,
    senderId: "ou_test",
    text: "在吗",
  };
}

describe.skipIf(!url)("conversation store (Postgres)", () => {
  let db: Db;
  beforeAll(async () => {
    db = createDb(url!);
    await runMigrations(db);
  });
  afterAll(async () => {
    await db.$client.end();
  });

  it("returns undefined for a redelivered message", async () => {
    const store = createConversationStore(db);
    const message = incoming();

    expect(await store.recordIncoming(message)).toBeDefined();
    expect(await store.recordIncoming(message)).toBeUndefined();
  });

  it("puts messages from the same chat in one Private Conversation", async () => {
    const store = createConversationStore(db);
    const first = incoming();
    const second = { ...incoming(), chatId: first.chatId };

    const a = await store.recordIncoming(first);
    const b = await store.recordIncoming(second);

    expect(a?.conversationId).toBe(b?.conversationId);
  });
});
