// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatBinding } from "../src/binding.tsx";
import { createQueryClient } from "../src/lib/queries.ts";

const provider = {
  id: "2b1e3b7d-bcb5-44a9-bb15-dbbd10d9fbb3",
  name: "OpenAI",
  protocol: "openai" as const,
  baseUrl: "https://api.openai.com/v1",
  apiKeyMask: "sk-••••",
};
const binding = { providerId: provider.id, model: "gpt-5", vision: true };
const fetchMock = vi.fn();
function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function setup() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <ChatBinding />
    </QueryClientProvider>,
  );
}
beforeEach(() => vi.stubGlobal("fetch", fetchMock));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("chat Binding", () => {
  it("shows the unbound state and validates the required Provider", async () => {
    fetchMock.mockResolvedValueOnce(json({ chat: null })).mockResolvedValueOnce(json([provider]));
    const user = userEvent.setup();
    setup();

    await user.click(await screen.findByRole("button", { name: "保存 Binding" }));

    expect(screen.getByText("尚未绑定 chat Capability。")).toBeInTheDocument();
    expect(await screen.findAllByRole("alert")).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("saves the complete Binding and refreshes its Query", async () => {
    let requestBody: unknown;
    fetchMock
      .mockResolvedValueOnce(json({ chat: null }))
      .mockResolvedValueOnce(json([provider]))
      .mockImplementationOnce(async (request: Request) => {
        requestBody = await request.clone().json();
        return json(binding);
      })
      .mockResolvedValueOnce(json({ chat: binding }));
    const user = userEvent.setup();
    setup();

    await user.selectOptions(await screen.findByLabelText("Provider"), provider.id);
    await user.type(screen.getByLabelText("模型"), binding.model);
    await user.click(screen.getByLabelText("支持图片输入"));
    await user.click(screen.getByRole("button", { name: "保存 Binding" }));

    expect(await screen.findByRole("status")).toHaveTextContent("chat Binding 已保存");
    expect(requestBody).toEqual(binding);
    expect(screen.getByLabelText("模型")).toHaveValue("gpt-5");
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("retains the draft after the server rejects a Binding", async () => {
    fetchMock
      .mockResolvedValueOnce(json({ chat: { ...binding, model: "old-model", vision: false } }))
      .mockResolvedValueOnce(json([provider]))
      .mockResolvedValueOnce(json({ error: "invalid-request" }, 400));
    const user = userEvent.setup();
    setup();
    const model = await screen.findByLabelText("模型");
    await user.clear(model);
    await user.type(model, "new-model");

    await user.click(screen.getByLabelText("支持图片输入"));
    await user.click(screen.getByRole("button", { name: "保存 Binding" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("请求内容无效");
    expect(model).toHaveValue("new-model");
    expect(screen.getByLabelText("支持图片输入")).toBeChecked();
    expect(screen.getByLabelText("Provider")).toHaveValue(provider.id);
  });

  it("disables Binding writes when no Provider is available", async () => {
    fetchMock.mockResolvedValueOnce(json({ chat: null })).mockResolvedValueOnce(json([]));

    setup();

    expect(await screen.findByRole("button", { name: "保存 Binding" })).toBeDisabled();
    expect(screen.getByText(/尚未配置 Provider/)).toBeInTheDocument();
  });
});
