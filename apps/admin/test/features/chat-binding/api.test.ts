// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chatBindingApi } from "../../../src/features/chat-binding/api.ts";

describe("chat Binding API", () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("accepts an absent chat Binding", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ chat: null }), {
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(chatBindingApi.get()).resolves.toEqual({ chat: null });
  });
});
