// @vitest-environment jsdom
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "../src/app.tsx";
import { fetchMock, json, renderWithQuery } from "./test-utils.tsx";

function setup() {
  return renderWithQuery(<App />);
}

describe("Admin application", () => {
  it("loads the User with Query and logs out through its mutation lifecycle", async () => {
    let finishLogout!: (response: Response) => void;
    const logoutResponse = new Promise<Response>((resolve) => {
      finishLogout = resolve;
    });
    const replace = vi.fn();
    vi.stubGlobal("location", { origin: window.location.origin, replace });
    fetchMock
      .mockResolvedValueOnce(json({ openId: "ou_123", name: "Ada" }))
      .mockResolvedValueOnce(json([]))
      .mockResolvedValueOnce(json({ chat: null }))
      .mockImplementationOnce(() => logoutResponse);
    const user = userEvent.setup();

    setup();
    expect(screen.getByRole("status")).toHaveTextContent("正在加载管理台");

    await user.click(await screen.findByRole("button", { name: "退出登录" }));
    expect(screen.getByRole("button", { name: "正在退出…" })).toBeDisabled();

    await act(async () => finishLogout(new Response(null, { status: 204 })));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/auth/feishu/login"));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("你好，Ada");
  });

  it("redirects expired sessions for queries as well as mutations", async () => {
    const replace = vi.fn();
    vi.stubGlobal("location", { origin: window.location.origin, replace });
    fetchMock.mockResolvedValue(json({ error: "Unauthorized" }, 401));

    setup();

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/auth/feishu/login"));
    expect(await screen.findByRole("alert")).toHaveTextContent("登录已过期");
  });
});
