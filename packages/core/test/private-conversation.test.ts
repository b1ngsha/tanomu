import { MockLanguageModelV4 } from "ai/test";
import { describe, expect, it } from "vitest";
import {
  replyToPrivateMessage,
  type ConversationStore,
  type IncomingMessage,
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

const message: IncomingMessage = { id: "m1", chatId: "c1", senderId: "u1", text: "在吗" };

describe("replyToPrivateMessage", () => {
  it("replies with the model's text and records the reply", async () => {
    const { store, replies } = memoryStore();
    const { send, sent } = recordingSend();

    await replyToPrivateMessage(message, { store, model: fakeModel("在，说吧"), send });

    expect(sent).toEqual([{ chatId: "c1", text: "在，说吧" }]);
    expect(replies).toEqual([
      { conversationId: "conv-c1", text: "在，说吧", feishuMessageId: "sent-1" },
    ]);
  });

  it("ignores a redelivered message", async () => {
    const { store } = memoryStore();
    const { send, sent } = recordingSend();
    const deps = { store, model: fakeModel("在"), send };

    await replyToPrivateMessage(message, deps);
    await replyToPrivateMessage(message, deps);

    expect(sent).toHaveLength(1);
  });

  it("declines non-text messages without calling the model", async () => {
    const { store } = memoryStore();
    const { send, sent } = recordingSend();
    const model = fakeModel("unused");

    await replyToPrivateMessage({ ...message, text: undefined }, { store, model, send });

    expect(model.doGenerateCalls).toHaveLength(0);
    expect(sent[0]?.text).toContain("看不了");
  });
});
