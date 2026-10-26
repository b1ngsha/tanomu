// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { provider } from "../../../test/fixtures.ts";
import { fetchMock, json, renderWithQuery } from "../../../test/test-utils.tsx";
import { Providers } from "./providers-section.tsx";

function setup() {
  return renderWithQuery(<Providers />);
}

describe("Providers", () => {
  it("validates a new Provider with the shared schema before writing", async () => {
    fetchMock.mockResolvedValueOnce(json([]));
    const user = userEvent.setup();
    setup();

    await user.click(await screen.findByRole("button", { name: "保存 Provider" }));

    expect(await screen.findAllByRole("alert")).toHaveLength(3);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("creates a Provider and displays the refreshed server state", async () => {
    fetchMock
      .mockResolvedValueOnce(json([]))
      .mockResolvedValueOnce(json(provider, 201))
      .mockResolvedValueOnce(json([provider]));
    const user = userEvent.setup();
    setup();
    await user.type(await screen.findByLabelText("名称"), "OpenAI");
    await user.type(screen.getByLabelText("Base URL"), provider.baseUrl);
    await user.type(screen.getByLabelText("API Key"), "secret");

    await user.click(screen.getByRole("button", { name: "保存 Provider" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Provider 已保存");
    expect(screen.getByRole("heading", { name: "OpenAI" })).toBeInTheDocument();
    expect(screen.getByLabelText("API Key")).toHaveValue("");
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ method: "POST" }),
      expect.anything(),
    );
  });

  it("keeps edits and the saved key after a rejected update", async () => {
    fetchMock
      .mockResolvedValueOnce(json([provider]))
      .mockResolvedValueOnce(json({ error: "duplicate-provider-name" }, 409));
    const user = userEvent.setup();
    setup();

    await user.click(await screen.findByRole("button", { name: "编辑 OpenAI" }));
    const name = screen.getByLabelText("名称");
    await user.clear(name);
    await user.type(name, "Changed");
    expect(screen.getByLabelText("API Key")).toHaveValue("");
    expect(screen.getByPlaceholderText("sk-••••（留空保持不变）")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "保存 Provider" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Provider 名称已存在");
    expect(name).toHaveValue("Changed");
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ method: "PATCH" }),
      expect.anything(),
    );
  });

  it("refreshes before allowing a repeat after an uncertain write", async () => {
    fetchMock
      .mockResolvedValueOnce(json([]))
      .mockRejectedValueOnce(new TypeError("connection lost"))
      .mockResolvedValueOnce(json([provider]));
    const user = userEvent.setup();
    setup();
    await user.type(await screen.findByLabelText("名称"), "OpenAI");
    await user.type(screen.getByLabelText("Base URL"), provider.baseUrl);
    await user.type(screen.getByLabelText("API Key"), "secret");

    await user.click(screen.getByRole("button", { name: "保存 Provider" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("请求结果未知");
    expect(screen.getByRole("heading", { name: "OpenAI" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("keeps writes disabled until reconciliation succeeds", async () => {
    fetchMock
      .mockResolvedValueOnce(json([]))
      .mockRejectedValueOnce(new TypeError("connection lost"))
      .mockRejectedValueOnce(new TypeError("read failed"))
      .mockResolvedValueOnce(json([]));
    const user = userEvent.setup();
    setup();
    await user.type(await screen.findByLabelText("名称"), "OpenAI");
    await user.type(screen.getByLabelText("Base URL"), provider.baseUrl);
    await user.type(screen.getByLabelText("API Key"), "secret");

    await user.click(screen.getByRole("button", { name: "保存 Provider" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "保存 Provider" })).toBeDisabled(),
    );

    await user.click(screen.getByRole("button", { name: "重新加载" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "保存 Provider" })).toBeEnabled(),
    );
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("confirms deletion and keeps an in-use Provider", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock
      .mockResolvedValueOnce(json([provider]))
      .mockResolvedValueOnce(json({ error: "provider-in-use" }, 409));
    const user = userEvent.setup();
    setup();

    await user.click(await screen.findByRole("button", { name: "删除 OpenAI" }));

    expect(window.confirm).toHaveBeenCalledWith("删除 Provider「OpenAI」？");
    expect(await screen.findByRole("alert")).toHaveTextContent("Provider 正在被使用");
    expect(screen.getByRole("heading", { name: "OpenAI" })).toBeInTheDocument();
  });
});
