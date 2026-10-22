import type { LlmCallLog } from "@tanomu/core";
import type { Db } from "./db/client.ts";
import { llmCalls } from "./db/schema.ts";

export function createLlmCallLog(db: Db): LlmCallLog {
  return {
    async record(call) {
      await db.insert(llmCalls).values({
        ...call,
        response: call.response ?? null,
        inputTokens: call.inputTokens ?? null,
        outputTokens: call.outputTokens ?? null,
        error: call.error ?? null,
      });
    },
  };
}
