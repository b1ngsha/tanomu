// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { fetchMock, json } from "../../../test/test-utils.tsx";
import { chatBindingApi } from "./api.ts";

describe("chat Binding API", () => {
  it("accepts an absent chat Binding", async () => {
    fetchMock.mockResolvedValue(json({ chat: null }));

    await expect(chatBindingApi.get()).resolves.toEqual({ chat: null });
  });
});
