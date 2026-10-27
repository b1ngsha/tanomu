// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { provider } from "../../../test/fixtures.ts";
import { fetchMock, json, renderWithQuery } from "../../../test/test-utils.tsx";
import { ChatBinding } from "./chat-binding-section.tsx";

const binding = { providerId: provider.id, model: "gpt-5", vision: true };

function setup() {
  return renderWithQuery(<ChatBinding />);
}

describe("chat Binding", () => {
  it("shows the unbound state and validates the required Provider", async () => {
    fetchMock.mockResolvedValueOnce(json({ chat: null })).mockResolvedValueOnce(json([provider]));
    const user = userEvent.setup();
    setup();

    await user.click(await screen.findByRole("button", { name: "保存 Binding" }));
    expect(screen.getByText("尚未绑定 chat Capability。")).toBeInTheDocument();
    expect(await screen.findAllByRole("alert")).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const select = screen.getByLabelText("Provider");
    expect(select).toHaveAttribute("aria-invalid", "true");
    expect(select).toHaveAccessibleDescription("请选择 Provider");
    expect(select).toHaveFocus();
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

  it("refreshes the Binding before allowing a repeat after an uncertain save", async () => {
    fetchMock
      .mockResolvedValueOnce(json({ chat: binding }))
      .mockResolvedValueOnce(json([provider]))
      .mockRejectedValueOnce(new TypeError("connection lost"))
      .mockResolvedValueOnce(json({ chat: binding }));
    const user = userEvent.setup();
    setup();

    await user.click(await screen.findByRole("button", { name: "保存 Binding" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("请求结果未知");
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      expect.objectContaining({ method: "GET", url: expect.stringMatching(/capabilities$/) }),
      expect.anything(),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "保存 Binding" })).toBeEnabled());
  });

  it("refreshes the Providers when the selected Provider was deleted", async () => {
    fetchMock
      .mockResolvedValueOnce(json({ chat: binding }))
      .mockResolvedValueOnce(json([provider]))
      .mockResolvedValueOnce(json({ error: "provider-not-found" }, 404))
      .mockResolvedValueOnce(json([]));
    const user = userEvent.setup();
    setup();

    await user.click(await screen.findByRole("button", { name: "保存 Binding" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Provider 已不存在");
    expect(await screen.findByText(/尚未配置 Provider/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("disables Binding writes when no Provider is available", async () => {
    fetchMock.mockResolvedValueOnce(json({ chat: null })).mockResolvedValueOnce(json([]));

    setup();

    expect(await screen.findByRole("button", { name: "保存 Binding" })).toBeDisabled();
    expect(screen.getByText(/尚未配置 Provider/)).toBeInTheDocument();
  });
});
