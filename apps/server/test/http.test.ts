import { expect, test, vi } from "vitest";
import { createHttpApp } from "../src/http.ts";
import type { ProviderStore } from "../src/provider-store.ts";
import type { ChatBindingStore } from "../src/chat-binding-store.ts";

const secret = "test-only-session-secret-with-32-characters";
const user = { openId: "ou_test", name: "Ada" };
const oauth = {
  authorizeUrl: (state: string) => `https://feishu.test/authorize?state=${state}`,
  exchange: async (code: string) => {
    expect(code).toBe("valid-code");
    return user;
  },
};
const chatBindingStore: ChatBindingStore = {
  getChatBinding: async () => null,
  putChatBinding: async () => {
    throw new Error("not used");
  },
};
const providerStore: ProviderStore = {
  listProviders: async () => [],
  createProvider: async () => {
    throw new Error("not used");
  },
  updateProvider: async () => {
    throw new Error("not used");
  },
  deleteProvider: async () => {
    throw new Error("not used");
  },
};
const app = createHttpApp({ oauth, sessionSecret: secret, providerStore, chatBindingStore });

function cookieOf(response: Response, name: string) {
  return response.headers
    .getSetCookie()
    .find((value) => value.startsWith(`${name}=`))!
    .split(";")[0]!;
}

test("login redirects to Feishu with a short-lived signed state cookie", async () => {
  const response = await app.request("/auth/feishu/login");
  expect(response.status).toBe(302);
  const url = new URL(response.headers.get("location")!);
  expect(url.origin).toBe("https://feishu.test");
  expect(url.searchParams.get("state")).toBeTruthy();
  expect(cookieOf(response, "tanomu_oauth_state")).not.toBe(
    `tanomu_oauth_state=${url.searchParams.get("state")}`,
  );
  expect(response.headers.get("set-cookie")).toContain("Max-Age=600");
  expect(response.headers.get("set-cookie")).toContain("HttpOnly");
});

test("callback rejects missing or mismatched state without a session", async () => {
  const login = await app.request("/auth/feishu/login");

  for (const cookie of ["", cookieOf(login, "tanomu_oauth_state")]) {
    const response = await app.request("/auth/feishu/callback?state=wrong&code=valid-code", {
      headers: { cookie },
    });
    expect(response.status).toBe(400);
    expect(response.headers.get("set-cookie") ?? "").not.toContain("tanomu_session=");
  }
});

test("valid callback signs in the User and exposes their name", async () => {
  const login = await app.request("/auth/feishu/login");
  const state = new URL(login.headers.get("location")!).searchParams.get("state");

  const callback = await app.request(`/auth/feishu/callback?state=${state}&code=valid-code`, {
    headers: { cookie: cookieOf(login, "tanomu_oauth_state") },
  });
  expect(callback.status).toBe(302);
  expect(callback.headers.get("location")).toBe("/");
  expect(callback.headers.get("set-cookie")).toContain("Max-Age=604800");

  const response = await app.request("/api/me", {
    headers: { cookie: cookieOf(callback, "tanomu_session") },
  });
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual(user);
});

test("sessions expire after seven days even if the cookie is retained", async () => {
  const login = await app.request("/auth/feishu/login");
  const state = new URL(login.headers.get("location")!).searchParams.get("state");

  const callback = await app.request(`/auth/feishu/callback?state=${state}&code=valid-code`, {
    headers: { cookie: cookieOf(login, "tanomu_oauth_state") },
  });

  vi.useFakeTimers();
  try {
    vi.setSystemTime(Date.now() + 8 * 86400_000);

    const response = await app.request("/api/me", {
      headers: { cookie: cookieOf(callback, "tanomu_session") },
    });
    expect(response.status).toBe(401);
  } finally {
    vi.useRealTimers();
  }
});

test("callback rejects an expired state and a denied authorization", async () => {
  const login = await app.request("/auth/feishu/login");
  const state = new URL(login.headers.get("location")!).searchParams.get("state");
  const headers = { cookie: cookieOf(login, "tanomu_oauth_state") };

  expect(
    (await app.request(`/auth/feishu/callback?state=${state}&error=access_denied`, { headers }))
      .status,
  ).toBe(400);

  vi.useFakeTimers();
  try {
    vi.setSystemTime(Date.now() + 601_000);

    expect(
      (await app.request(`/auth/feishu/callback?state=${state}&code=valid-code`, { headers }))
        .status,
    ).toBe(400);
  } finally {
    vi.useRealTimers();
  }
});

test("failed OAuth exchange does not leak upstream errors or create a session", async () => {
  const failing = createHttpApp({
    sessionSecret: secret,
    oauth: {
      ...oauth,
      exchange: async () => {
        throw new Error("sensitive upstream details");
      },
    },
    providerStore,
    chatBindingStore,
  });
  const login = await failing.request("/auth/feishu/login");
  const state = new URL(login.headers.get("location")!).searchParams.get("state");

  const response = await failing.request(`/auth/feishu/callback?state=${state}&code=valid-code`, {
    headers: { cookie: cookieOf(login, "tanomu_oauth_state") },
  });
  expect(response.status).toBe(502);
  expect(await response.text()).not.toContain("sensitive");
  expect(response.headers.get("set-cookie")).not.toContain("tanomu_session=");
});

test("logout clears the session cookie", async () => {
  const response = await app.request("/auth/logout", { method: "POST" });
  expect(response.status).toBe(204);
  expect(response.headers.get("set-cookie")).toContain("tanomu_session=;");
  expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
});

test("admin APIs reject missing and forged sessions", async () => {
  for (const path of ["/api/me", "/api/future"]) {
    for (const cookie of [
      "",
      'tanomu_session={"openId":"ou_forged"}',
      "tanomu_session=forged.signature",
    ]) {
      const response = await app.request(path, { headers: { cookie } });
      expect(response.status).toBe(401);
    }
  }
});
