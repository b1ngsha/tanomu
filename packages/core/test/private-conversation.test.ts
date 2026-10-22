import { MockLanguageModelV4 } from "ai/test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createMessageBatcher,
  recordPrivateMessage,
  replyToPrivateMessage,
  replyToPrivateMessages,
  type ConversationStore,
  type IncomingMessage,
  type LlmCall,
  type LlmCallLog,
  type MessageBatcher,
  type RecordedMessage,
  type ReplyDeps,
} from "../src/index.ts";

function fakeModel(reply: string, beforeGenerate?: () => Promise<void>) {
  return new MockLanguageModelV4({
    doGenerate: async () => {
      await beforeGenerate?.();
      return {
        content: [{ type: "text" as const, text: reply }],
        finishReason: { unified: "stop" as const, raw: "stop" },
        usage: {
          inputTokens: { total: 1, noCache: 1, cacheRead: 0, cacheWrite: 0 },
          outputTokens: { total: 1, text: 1, reasoning: 0 },
        },
        warnings: [],
      };
    },
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

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function createTestBatcher(deps: ReplyDeps) {
  const flushes: Array<Promise<void>> = [];
  const batcher = createMessageBatcher<RecordedMessage>({
    windowMs: 2_500,
    onFlush: (chatId, items) => {
      const flush = replyToPrivateMessages(chatId, items, deps);
      flushes.push(flush);
      return flush;
    },
  });
  return { batcher, flushes };
}

function setupBatch(model = fakeModel("好的")) {
  const { store, replies } = memoryStore();
  const { send, sent } = recordingSend();
  const { llmCallLog, calls } = recordingLlmCallLog();
  const deps = { store, model, send, llmCallLog };
  const { batcher, flushes } = createTestBatcher(deps);
  return { store, replies, sent, calls, model, batcher, flushes };
}

async function addRecorded(
  batcher: MessageBatcher<RecordedMessage>,
  store: ConversationStore,
  incoming: IncomingMessage,
): Promise<void> {
  const recorded = await recordPrivateMessage(incoming, { store });
  if (!recorded) throw new Error("expected message to be recorded");
  batcher.add(incoming.chatId, recorded);
}

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

describe("private message batching", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("resets the window on each message and merges texts in order", async () => {
    const { store, sent, calls, model, batcher, flushes } = setupBatch();

    const texts = ["在吗", "问你个事", "xxx 怎么搞"];
    for (const [index, text] of texts.entries()) {
      await addRecorded(batcher, store, { ...message, id: `m${index}`, text });
      if (index < texts.length - 1) await vi.advanceTimersByTimeAsync(1_000);
    }
    expect(
      await recordPrivateMessage({ ...message, id: "m0", text: "在吗" }, { store }),
    ).toBeUndefined();
    await vi.advanceTimersByTimeAsync(2_500);
    await Promise.all(flushes);

    expect(model.doGenerateCalls).toHaveLength(1);
    expect(calls[0]?.request).toEqual({ prompt: "在吗\n问你个事\nxxx 怎么搞" });
    expect(sent).toEqual([{ chatId: "c1", text: "好的" }]);
  });

  it("ignores non-text messages in a mixed batch", async () => {
    const { store, sent, calls, model, batcher, flushes } = setupBatch();

    await addRecorded(batcher, store, { ...message, id: "m1", text: "在吗" });
    await addRecorded(batcher, store, { ...message, id: "m2", text: undefined });
    await addRecorded(batcher, store, { ...message, id: "m3", text: "问你个事" });
    await vi.advanceTimersByTimeAsync(2_500);
    await Promise.all(flushes);

    expect(model.doGenerateCalls).toHaveLength(1);
    expect(calls[0]?.request).toEqual({ prompt: "在吗\n问你个事" });
    expect(sent).toHaveLength(1);
  });

  it("declines a non-text-only batch without calling the model", async () => {
    const { store, replies, sent, model, batcher, flushes } = setupBatch(fakeModel("unused"));

    await addRecorded(batcher, store, { ...message, id: "m1", text: undefined });
    await addRecorded(batcher, store, { ...message, id: "m2", text: undefined });
    await vi.advanceTimersByTimeAsync(2_500);
    await Promise.all(flushes);

    expect(model.doGenerateCalls).toHaveLength(0);
    expect(sent[0]?.text).toContain("看不了");
    expect(replies).toHaveLength(1);
  });

  it("replies separately when messages are more than a window apart", async () => {
    const { store, sent, calls, batcher, flushes } = setupBatch();

    await addRecorded(batcher, store, { ...message, id: "m1", text: "在吗" });
    await vi.advanceTimersByTimeAsync(3_000);
    await Promise.all(flushes);

    await addRecorded(batcher, store, { ...message, id: "m2", text: "问你个事" });
    await vi.advanceTimersByTimeAsync(2_500);
    await Promise.all(flushes);

    expect(calls.map((call) => call.request)).toEqual([{ prompt: "在吗" }, { prompt: "问你个事" }]);
    expect(sent).toHaveLength(2);
  });

  it("starts a new window for a message arriving during an in-flight reply", async () => {
    const firstCall = deferred();
    let generations = 0;
    const model = fakeModel("好的", async () => {
      generations += 1;
      if (generations === 1) await firstCall.promise;
    });
    const { store, sent, calls, batcher, flushes } = setupBatch(model);

    await addRecorded(batcher, store, { ...message, id: "m1", text: "在吗" });
    await vi.advanceTimersByTimeAsync(2_500);
    expect(flushes).toHaveLength(1);
    expect(generations).toBe(1);

    await addRecorded(batcher, store, { ...message, id: "m2", text: "问你个事" });
    await vi.advanceTimersByTimeAsync(2_500);
    expect(flushes).toHaveLength(2);
    await flushes[1];

    expect(generations).toBe(2);
    expect(sent).toEqual([{ chatId: "c1", text: "好的" }]);

    firstCall.resolve();
    await flushes[0];

    expect(sent).toHaveLength(2);
    expect(calls).toHaveLength(2);
    expect(calls.map((call) => call.request)).toEqual(
      expect.arrayContaining([{ prompt: "在吗" }, { prompt: "问你个事" }]),
    );
  });
});
