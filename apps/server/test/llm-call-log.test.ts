import { randomUUID } from "node:crypto";
import { eq } from "drizzle-orm";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createDb, runMigrations, type Db } from "../src/db/client.ts";
import { conversations, llmCalls } from "../src/db/schema.ts";
import { createLlmCallLog } from "../src/llm-call-log.ts";

const url = process.env.TEST_DATABASE_URL;

describe.skipIf(!url)("LLM call log (Postgres)", () => {
  let db: Db;
  beforeAll(async () => {
    db = createDb(url!);
    await runMigrations(db);
  });
  afterAll(async () => {
    await db.$client.end();
  });

  it("round-trips the full request and response JSON for a Conversation", async () => {
    const [conversation] = await db
      .insert(conversations)
      .values({ kind: "private", feishuChatId: `oc_${randomUUID()}` })
      .returning({ id: conversations.id });
    const request = {
      instructions: "You are tanomu.",
      messages: [{ role: "user", content: "在吗" }],
    };
    const response = [{ role: "assistant", content: [{ type: "text", text: "在" }] }];

    await createLlmCallLog(db).record({
      capability: "chat",
      conversationId: conversation!.id,
      provider: "openai.chat",
      model: "gpt-test",
      request,
      response,
      inputTokens: 5,
      outputTokens: 2,
      latencyMs: 12,
      error: undefined,
    });

    const rows = await db
      .select()
      .from(llmCalls)
      .where(eq(llmCalls.conversationId, conversation!.id));
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      capability: "chat",
      conversationId: conversation!.id,
      provider: "openai.chat",
      model: "gpt-test",
      request,
      response,
      inputTokens: 5,
      outputTokens: 2,
      latencyMs: 12,
      error: null,
    });
  });
});
