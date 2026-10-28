// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/app.tsx";
import { adminQueries, createQueryClient, useSaveProvider } from "../src/lib/queries.ts";

const provider = {
  id: "2b1e3b7d-bcb5-44a9-bb15-dbbd10d9fbb3",
  name: "OpenAI",
  protocol: "openai" as const,
  baseUrl: "https://api.openai.com/v1",
  apiKeyMask: "sk-••••",
};
const input = {
  name: "OpenAI",
  protocol: "openai" as const,
  baseUrl: "https://api.openai.com/v1",
  apiKey: "secret",
};
function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function setup() {
  const client = createQueryClient();
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, ...render(<App />, { wrapper }) };
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Admin application", () => {
  it("loads the User with Query and logs out through its mutation lifecycle", async () => {
    let finishLogout!: (response: Response) => void;
    const logoutResponse = new Promise<Response>((resolve) => {
      finishLogout = resolve;
    });
    const replace = vi.fn();
    vi.stubGlobal("location", { origin: window.location.origin, replace });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ openId: "ou_123", name: "Ada" }))
      .mockResolvedValueOnce(json([]))
      .mockImplementationOnce(() => logoutResponse);
    vi.stubGlobal("fetch", fetchMock);
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
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ error: "Unauthorized" }, 401)));

    setup();

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/auth/feishu/login"));
    expect(await screen.findByRole("alert")).toHaveTextContent("登录已过期");
  });

  it("keeps a Provider save pending until its fresh query has reconciled", async () => {
    let finish!: (response: Response) => void;
    const refetch = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json([provider]))
      .mockResolvedValueOnce(json(provider, 201))
      .mockImplementationOnce(() => refetch);
    vi.stubGlobal("fetch", fetchMock);
    const client = createQueryClient();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () => ({ providers: useQuery(adminQueries.providers()), save: useSaveProvider() }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.providers.data).toEqual([provider]));

    act(() => result.current.save.mutate({ id: null, input }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(result.current.save.isPending).toBe(true);

    await act(async () => finish(json([{ ...provider, name: "Fresh" }])));

    await waitFor(() => expect(result.current.save.isPending).toBe(false));
    expect(client.getQueryData(adminQueries.providers().queryKey)).toEqual([
      { ...provider, name: "Fresh" },
    ]);
  });
});
