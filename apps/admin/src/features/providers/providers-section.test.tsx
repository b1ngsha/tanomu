// @vitest-environment jsdom
import { act, screen, waitFor } from "@testing-library/react";
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
    const name = screen.getByLabelText("名称");
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription("不能为空");
    expect(name).toHaveFocus();
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
    expect(screen.getByLabelText("名称")).toHaveValue("");
    expect(screen.getByLabelText("Base URL")).toHaveValue("");
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ method: "POST" }),
      expect.anything(),
    );
  });

  it("keeps edits and the saved key after a rejected update", async () => {
    let patch: unknown;
    fetchMock
      .mockResolvedValueOnce(json([provider]))
      .mockImplementationOnce(async (request: Request) => {
        patch = await request.json();
        return json({ error: "duplicate-provider-name" }, 409);
      });
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
    expect(patch).toEqual({ name: "Changed", protocol: "openai", baseUrl: provider.baseUrl });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("locks the edit draft through reconciliation and shows the saved server state", async () => {
    let finish!: (response: Response) => void;
    const refreshed = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    fetchMock
      .mockResolvedValueOnce(json([provider]))
      .mockResolvedValueOnce(json({ ...provider, name: "Changed" }))
      .mockImplementationOnce(() => refreshed);
    const user = userEvent.setup();
    setup();
    await user.click(await screen.findByRole("button", { name: "编辑 OpenAI" }));
    const name = screen.getByLabelText("名称");
    await user.clear(name);
    await user.type(name, "Changed");

    await user.click(screen.getByRole("button", { name: "保存 Provider" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));

    expect(name).toBeDisabled();
    expect(screen.getByLabelText("协议")).toBeDisabled();
    expect(screen.getByLabelText("API Key")).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消" })).toBeDisabled();

    await act(async () => finish(json([{ ...provider, name: "Changed" }])));

    expect(await screen.findByRole("status")).toHaveTextContent("Provider 已保存");
    expect(name).toBeEnabled();
    expect(name).toHaveValue("Changed");
    expect(screen.getByRole("heading", { name: "Changed" })).toBeInTheDocument();
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

  it("leaves the edit form when the Provider no longer exists", async () => {
    fetchMock
      .mockResolvedValueOnce(json([provider]))
      .mockResolvedValueOnce(json({ error: "provider-not-found" }, 404))
      .mockResolvedValueOnce(json([]));
    const user = userEvent.setup();
    setup();
    await user.click(await screen.findByRole("button", { name: "编辑 OpenAI" }));

    await user.click(screen.getByRole("button", { name: "保存 Provider" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("正在编辑的 Provider 已不存在");
    expect(screen.queryByRole("heading", { name: "OpenAI" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);

    await user.click(screen.getByRole("button", { name: "返回添加 Provider" }));
    expect(screen.getByRole("heading", { name: "添加 Provider" })).toBeInTheDocument();
  });

  it("deletes a Provider and leaves its edit form", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock
      .mockResolvedValueOnce(json([provider]))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(json([]));
    const user = userEvent.setup();
    setup();
    await user.click(await screen.findByRole("button", { name: "编辑 OpenAI" }));

    await user.click(screen.getByRole("button", { name: "删除 OpenAI" }));
    expect(await screen.findByText("尚未配置 Provider。")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "添加 Provider" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    ["an uncertain", new TypeError("connection lost"), "请求结果未知"],
    ["a missing", json({ error: "provider-not-found" }, 404), "Provider 已不存在"],
  ])("refreshes the list after %s delete", async (_, outcome, message) => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockResolvedValueOnce(json([provider]));
    if (outcome instanceof Error) fetchMock.mockRejectedValueOnce(outcome);
    else fetchMock.mockResolvedValueOnce(outcome);
    fetchMock.mockResolvedValueOnce(json([]));
    const user = userEvent.setup();
    setup();

    await user.click(await screen.findByRole("button", { name: "删除 OpenAI" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByRole("heading", { name: "OpenAI" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
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
