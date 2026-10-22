import { MockLanguageModelV4 } from "ai/test";
import { describe, expect, it } from "vitest";
import {
  replyToPrivateMessage,
  type ConversationStore,
  type IncomingMessage,
  type LlmCall,
  type LlmCallLog,
} from "../src/index.ts";

function fakeModel(reply: string) {
  return new MockLanguageModelV4({
    doGenerate: async () => ({
      content: [{ type: "text", text: reply }],
      finishReason: { unified: "stop", raw: "stop" },
      usage: {
        inputTokens: { total: 1, noCache: 1, cacheRead: 0, cacheWrite: 0 },
        outputTokens: { total: 1, text: 1, reasoning: 0 },
      },
      warnings: [],
    }),
  });
}

function memoryStore() {
  const seen = new Set<string>();
  const replies: Array<{ conversationId: string; text: string; feishuMessageId: string }> = [];
  const store: ConversationStore = {
    async recordIncoming(message) {
      if (seen.has(message.id)) return undefined;
      seen.add(message.id);
      return { conversationId: `conv-${message.chatId}` };
    },
    async recordReply(conversationId, reply) {
      replies.push({ conversationId, ...reply });
    },
  };
  return { store, replies };
}

function recordingSend() {
  const sent: Array<{ chatId: string; text: string }> = [];
  async function send(chatId: string, text: string): Promise<string> {
    sent.push({ chatId, text });
    return `sent-${sent.length}`;
  }
  return { send, sent };
}

function recordingLlmCallLog() {
  const calls: LlmCall[] = [];
  const llmCallLog: LlmCallLog = {
    async record(call) {
      calls.push(call);
    },
  };
  return { llmCallLog, calls };
}

const message: IncomingMessage = { id: "m1", chatId: "c1", senderId: "u1", text: "在吗" };

describe("replyToPrivateMessage", () => {
  it("replies with the model's text and records the reply", async () => {
    const { store, replies } = memoryStore();
    const { send, sent } = recordingSend();

    const { llmCallLog } = recordingLlmCallLog();

    await replyToPrivateMessage(message, { store, model: fakeModel("在，说吧"), send, llmCallLog });

    expect(sent).toEqual([{ chatId: "c1", text: "在，说吧" }]);
    expect(replies).toEqual([
      { conversationId: "conv-c1", text: "在，说吧", feishuMessageId: "sent-1" },
    ]);
  });

  it("ignores a redelivered message", async () => {
    const { store } = memoryStore();
    const { send, sent } = recordingSend();
    const { llmCallLog } = recordingLlmCallLog();
    const deps = { store, model: fakeModel("在"), send, llmCallLog };

    await replyToPrivateMessage(message, deps);
    await replyToPrivateMessage(message, deps);

    expect(sent).toHaveLength(1);
  });

  it("records one chat call linked to the Conversation", async () => {
    const { store } = memoryStore();
    const { send } = recordingSend();
    const { llmCallLog, calls } = recordingLlmCallLog();

    await replyToPrivateMessage(message, { store, model: fakeModel("在，说吧"), send, llmCallLog });

    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      capability: "chat",
      conversationId: "conv-c1",
      provider: "mock-provider",
      model: "mock-model-id",
      inputTokens: 1,
      outputTokens: 1,
      error: undefined,
    });
    expect(calls[0]?.latencyMs).toBeGreaterThanOrEqual(0);
    expect(JSON.stringify(calls[0]?.request)).toContain("在吗");
    expect(JSON.stringify(calls[0]?.response)).toContain("在，说吧");
  });

  it("records a failed model call and still fails the reply", async () => {
    const { store } = memoryStore();
    const { send, sent } = recordingSend();
    const { llmCallLog, calls } = recordingLlmCallLog();
    const model = new MockLanguageModelV4({
      doGenerate: async () => {
        throw new Error("provider down");
      },
    });

    await expect(
      replyToPrivateMessage(message, { store, model, send, llmCallLog }),
    ).rejects.toThrow("provider down");

    expect(sent).toHaveLength(0);
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ conversationId: "conv-c1", response: undefined });
    expect(calls[0]?.error).toContain("provider down");
  });

  it("still replies when recording the call fails", async () => {
    const { store } = memoryStore();
    const { send, sent } = recordingSend();
    const llmCallLog: LlmCallLog = {
      record: async () => {
        throw new Error("db down");
      },
    };

    await replyToPrivateMessage(message, { store, model: fakeModel("在"), send, llmCallLog });

    expect(sent).toEqual([{ chatId: "c1", text: "在" }]);
  });

  it("declines non-text messages without calling the model", async () => {
    const { store } = memoryStore();
    const { send, sent } = recordingSend();
    const model = fakeModel("unused");
    const { llmCallLog, calls } = recordingLlmCallLog();

    await replyToPrivateMessage(
      { ...message, text: undefined },
      { store, model, send, llmCallLog },
    );

    expect(model.doGenerateCalls).toHaveLength(0);
    expect(calls).toHaveLength(0);
    expect(sent[0]?.text).toContain("看不了");
  });
});
