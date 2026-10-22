import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMessageBatcher } from "../src/index.ts";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function recordingBatcher() {
  const flushes: Array<{ chatId: string; items: string[] }> = [];
  const batcher = createMessageBatcher<string>({
    windowMs: 2_500,
    onFlush: async (chatId, items) => {
      flushes.push({ chatId, items });
    },
  });
  return { batcher, flushes };
}

describe("createMessageBatcher", () => {
  it("resets the timer on each add and flushes items in arrival order", async () => {
    const { batcher, flushes } = recordingBatcher();

    batcher.add("c1", "在吗");
    await vi.advanceTimersByTimeAsync(1_000);
    batcher.add("c1", "问你个事");
    await vi.advanceTimersByTimeAsync(1_000);
    batcher.add("c1", "xxx 怎么搞");
    await vi.advanceTimersByTimeAsync(2_499);

    expect(flushes).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(1);

    expect(flushes).toEqual([{ chatId: "c1", items: ["在吗", "问你个事", "xxx 怎么搞"] }]);
  });

  it("keeps different chats independent", async () => {
    const { batcher, flushes } = recordingBatcher();

    batcher.add("c1", "a");
    await vi.advanceTimersByTimeAsync(1_000);
    batcher.add("c2", "b");
    await vi.advanceTimersByTimeAsync(1_500);

    expect(flushes).toEqual([{ chatId: "c1", items: ["a"] }]);

    await vi.advanceTimersByTimeAsync(1_000);

    expect(flushes).toEqual([
      { chatId: "c1", items: ["a"] },
      { chatId: "c2", items: ["b"] },
    ]);
  });

  it("logs flush errors instead of throwing", async () => {
    const error = new Error("model down");
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const batcher = createMessageBatcher<string>({
      windowMs: 2_500,
      onFlush: async () => {
        throw error;
      },
    });

    batcher.add("c1", "a");
    await vi.advanceTimersByTimeAsync(2_500);
    await Promise.resolve();

    expect(consoleError).toHaveBeenCalledWith("failed to flush messages for chat c1", error);
  });
});
