import { eq } from "drizzle-orm";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { createDb, runMigrations, type Db } from "../src/db/client.ts";
import { capabilityBindings, providers } from "../src/db/schema.ts";
import { createKeyCipher } from "../src/key-cipher.ts";
import { createHttpApp } from "../src/http.ts";
import { createProviderStore } from "../src/provider-store.ts";

const url = process.env.TEST_DATABASE_URL;
const sessionSecret = "test-only-session-secret-with-32-characters";
const cipher = createKeyCipher("0123456789abcdef".repeat(4));
const oauth = {
  authorizeUrl: (state: string) => `https://feishu.test/authorize?state=${state}`,
  exchange: async () => ({ openId: "ou_test", name: "Ada" }),
};

function cookieOf(response: Response, name: string): string {
  return response.headers
    .getSetCookie()
    .find((value) => value.startsWith(`${name}=`))!
    .split(";")[0]!;
}

describe.skipIf(!url)("Admin API (Postgres)", () => {
  let db: Db;
  let app: ReturnType<typeof createHttpApp>;

  async function sessionCookie(): Promise<string> {
    const login = await app.request("/auth/feishu/login");
    const state = new URL(login.headers.get("location")!).searchParams.get("state");
    const callback = await app.request(`/auth/feishu/callback?state=${state}&code=valid-code`, {
      headers: { cookie: cookieOf(login, "tanomu_oauth_state") },
    });
    return cookieOf(callback, "tanomu_session");
  }

  async function request(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set("cookie", await sessionCookie());
    return app.request(path, { ...init, headers });
  }

  beforeAll(async () => {
    db = createDb(url!);
    await runMigrations(db);
    app = createHttpApp({
      oauth,
      sessionSecret,
      providerStore: createProviderStore(db, cipher),
    });
  });
  beforeEach(async () => {
    await db.delete(capabilityBindings);
    await db.delete(providers);
  });
  afterAll(async () => {
    await db.$client.end();
  });

  it("rejects every Provider route without a session", async () => {
    const requests = [
      ["/api/providers", undefined],
      ["/api/providers", { method: "POST", body: "{}" }],
      ["/api/providers/not-a-provider", { method: "PATCH", body: "{}" }],
      ["/api/providers/not-a-provider", { method: "DELETE" }],
    ] as const;

    for (const [path, init] of requests) {
      expect((await app.request(path, init)).status).toBe(401);
    }
  });

  it("creates and lists a Provider with only a masked key", async () => {
    const response = await request("/api/providers", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: "  Relay  ",
        protocol: "anthropic",
        baseUrl: "https://relay.example.com/v1",
        apiKey: "sk-abcdefghijklmnop",
      }),
    });
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({
      id: expect.any(String),
      name: "Relay",
      protocol: "anthropic",
      baseUrl: "https://relay.example.com/v1",
      apiKeyMask: "sk••••mnop",
    });

    const listed = await request("/api/providers");
    const body = await listed.json();
    expect(body).toEqual([
      {
        id: expect.any(String),
        name: "Relay",
        protocol: "anthropic",
        baseUrl: "https://relay.example.com/v1",
        apiKeyMask: "sk••••mnop",
      },
    ]);
    expect(JSON.stringify(body)).not.toContain("abcdefghijklmnop");

    const [stored] = await db.select().from(providers);
    expect(stored!.apiKey).not.toContain("abcdefghijklmnop");
    expect(cipher.decrypt(stored!.apiKey)).toBe("sk-abcdefghijklmnop");
  });

  it("validates Provider input and rejects case-insensitive duplicate names", async () => {
    const invalid = [
      { name: "", protocol: "openai", baseUrl: "https://api.example.com", apiKey: "key" },
      { name: "Name", protocol: "invalid", baseUrl: "https://api.example.com", apiKey: "key" },
      { name: "Name", protocol: "openai", baseUrl: "ftp://api.example.com", apiKey: "key" },
      { name: "Name", protocol: "openai", baseUrl: "https://api.example.com", apiKey: "" },
    ];
    for (const body of invalid) {
      expect(
        (
          await request("/api/providers", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(body),
          })
        ).status,
      ).toBe(400);
    }

    const created = await request("/api/providers", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: "Default",
        protocol: "openai",
        baseUrl: "https://api.example.com",
        apiKey: "key",
      }),
    });
    expect(created.status).toBe(201);
    const duplicate = await request("/api/providers", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: " default ",
        protocol: "openai",
        baseUrl: "https://api.example.com",
        apiKey: "key",
      }),
    });
    expect(duplicate.status).toBe(409);
  });

  it("updates a Provider and keeps its key when omitted or empty", async () => {
    const created = await request("/api/providers", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: "Before",
        protocol: "openai",
        baseUrl: "https://old.example.com",
        apiKey: "old-secret-key-1234",
      }),
    });
    const provider = await created.json();
    const oldKey = "old-secret-key-1234";
    await db
      .update(providers)
      .set({ updatedAt: new Date("2000-01-01T00:00:00Z") })
      .where(eq(providers.id, provider.id));
    const [beforeUpdate] = await db.select().from(providers);

    for (const apiKey of [undefined, ""]) {
      const response = await request(`/api/providers/${provider.id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: " After ", apiKey }),
      });
      expect(response.status).toBe(200);
      expect((await response.json()).apiKeyMask).toBe("ol••••1234");
      const [stored] = await db.select().from(providers);
      expect(cipher.decrypt(stored!.apiKey)).toBe(oldKey);
    }
    const [afterUpdate] = await db.select().from(providers);
    expect(afterUpdate!.updatedAt.getTime()).toBeGreaterThan(beforeUpdate!.updatedAt.getTime());
  });

  it("replaces a Provider key without returning plaintext or ciphertext", async () => {
    const [provider] = await db
      .insert(providers)
      .values({
        name: "Replace key",
        protocol: "openai",
        baseUrl: "https://old.example.com",
        apiKey: cipher.encrypt("old-secret-key-1234"),
      })
      .returning();
    const response = await request(`/api/providers/${provider!.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        protocol: "google",
        baseUrl: "https://new.example.com",
        apiKey: "new-secret-key-5678",
      }),
    });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      id: provider!.id,
      name: "Replace key",
      protocol: "google",
      baseUrl: "https://new.example.com",
      apiKeyMask: "ne••••5678",
    });
    const [stored] = await db.select().from(providers);
    expect(stored!.apiKey).not.toBe("new-secret-key-5678");
    expect(cipher.decrypt(stored!.apiKey)).toBe("new-secret-key-5678");
  });

  it("rejects malformed requests, missing Providers and conflicting edits", async () => {
    const input = {
      protocol: "openai" as const,
      baseUrl: "https://api.example.com",
      apiKey: cipher.encrypt("key"),
    };
    const rows = await db
      .insert(providers)
      .values([
        { ...input, name: "First" },
        { ...input, name: "Second" },
      ])
      .returning();
    const cases = [
      ["/api/providers", "POST", "{", 400],
      [`/api/providers/${rows[0]!.id}`, "PATCH", "{", 400],
      ["/api/providers/invalid-id", "PATCH", "{}", 400],
      ["/api/providers/invalid-id", "DELETE", undefined, 400],
      [`/api/providers/${crypto.randomUUID()}`, "PATCH", "{}", 404],
      [`/api/providers/${rows[1]!.id}`, "PATCH", JSON.stringify({ name: " first " }), 409],
    ] as const;
    for (const [path, method, body, status] of cases) {
      const response = await request(path, { method, ...(body === undefined ? {} : { body }) });
      expect(response.status).toBe(status);
      expect(response.headers.get("content-type")).toContain("application/json");
    }
  });

  it("returns a generic error when a stored key cannot be decrypted", async () => {
    const [provider] = await db
      .insert(providers)
      .values({
        name: "Broken",
        protocol: "openai",
        baseUrl: "https://api.example.com",
        apiKey: "not-an-encrypted-key",
      })
      .returning();
    for (const [path, init] of [
      ["/api/providers", {}],
      [
        `/api/providers/${provider!.id}`,
        { method: "PATCH", body: JSON.stringify({ name: "Renamed" }) },
      ],
    ] as const) {
      const response = await request(path, init);
      expect(response.status).toBe(500);
      expect(await response.json()).toEqual({ error: "internal-error" });
    }
  });

  it("reads an unbound chat Capability and requires a session for Binding routes", async () => {
    for (const [path, init] of [
      ["/api/capabilities", {}],
      ["/api/capabilities/chat", { method: "PUT", body: "{}" }],
    ] as const) {
      expect((await app.request(path, init)).status).toBe(401);
    }
    const response = await request("/api/capabilities");
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ chat: null });
  });

  it("creates and replaces the chat Binding without exposing Provider keys", async () => {
    const rows = await db
      .insert(providers)
      .values([
        {
          name: "First",
          protocol: "openai",
          baseUrl: "https://api.example.com",
          apiKey: cipher.encrypt("first-secret-key-1234"),
        },
        {
          name: "Second",
          protocol: "anthropic",
          baseUrl: "https://api.example.com",
          apiKey: cipher.encrypt("second-secret-key-5678"),
        },
      ])
      .returning();
    const first = { providerId: rows[0]!.id, model: "model-one", vision: false };
    const create = await request("/api/capabilities/chat", {
      method: "PUT",
      body: JSON.stringify(first),
    });
    expect(create.status).toBe(200);
    expect(await create.json()).toEqual(first);
    await db.update(capabilityBindings).set({ updatedAt: new Date("2000-01-01T00:00:00Z") });
    const second = { providerId: rows[1]!.id, model: "model-two", vision: true };
    const update = await request("/api/capabilities/chat", {
      method: "PUT",
      body: JSON.stringify({ ...second, model: " model-two " }),
    });
    expect(update.status).toBe(200);
    expect(await update.json()).toEqual(second);
    expect(await (await request("/api/capabilities")).json()).toEqual({ chat: second });
    const bindings = await db.select().from(capabilityBindings);
    expect(bindings).toHaveLength(1);
    expect(bindings[0]!.updatedAt.getTime()).toBeGreaterThan(
      new Date("2000-01-01T00:00:00Z").getTime(),
    );
    expect((await request(`/api/providers/${rows[0]!.id}`, { method: "DELETE" })).status).toBe(204);
    expect((await request(`/api/providers/${rows[1]!.id}`, { method: "DELETE" })).status).toBe(409);
  });

  it("rejects invalid Binding input and unknown Providers without replacing the Binding", async () => {
    const [provider] = await db
      .insert(providers)
      .values({
        name: "Bound",
        protocol: "openai",
        baseUrl: "https://api.example.com",
        apiKey: cipher.encrypt("key"),
      })
      .returning();
    const binding = { providerId: provider!.id, model: "original", vision: false };
    expect(
      (await request("/api/capabilities/chat", { method: "PUT", body: JSON.stringify(binding) }))
        .status,
    ).toBe(200);
    const cases = [
      ["{", 400],
      [JSON.stringify({ ...binding, model: "  " }), 400],
      [JSON.stringify({ ...binding, providerId: "invalid" }), 400],
      [JSON.stringify({ ...binding, vision: "true" }), 400],
      [JSON.stringify({ providerId: provider!.id, model: "model" }), 400],
      [JSON.stringify({ ...binding, providerId: crypto.randomUUID() }), 404],
    ] as const;
    for (const [body, status] of cases) {
      const response = await request("/api/capabilities/chat", { method: "PUT", body });
      expect(response.status).toBe(status);
      expect(await response.json()).toEqual({
        error: status === 404 ? "provider-not-found" : "invalid-request",
      });
      expect(await (await request("/api/capabilities")).json()).toEqual({ chat: binding });
    }
  });

  it("serializes concurrent Binding creation into one complete Binding", async () => {
    const [provider] = await db
      .insert(providers)
      .values({
        name: "Concurrent",
        protocol: "openai",
        baseUrl: "https://api.example.com",
        apiKey: cipher.encrypt("key"),
      })
      .returning();
    const choices = [
      { providerId: provider!.id, model: "first", vision: false },
      { providerId: provider!.id, model: "second", vision: true },
    ];
    const responses = await Promise.all(
      choices.map((binding) =>
        request("/api/capabilities/chat", {
          method: "PUT",
          body: JSON.stringify(binding),
        }),
      ),
    );
    for (const [index, response] of responses.entries()) {
      expect(response.status).toBe(200);
      expect(await response.json()).toEqual(choices[index]);
    }
    const { chat } = await (await request("/api/capabilities")).json();
    expect(choices).toContainEqual(chat);
    expect(await db.select().from(capabilityBindings)).toHaveLength(1);
  });

  it("deletes unbound Providers and rejects deleting a bound Provider", async () => {
    const create = async (name: string) =>
      request("/api/providers", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name,
          protocol: "openai",
          baseUrl: "https://api.example.com",
          apiKey: "key",
        }),
      });
    const unbound = await (await create("Unbound")).json();
    expect((await request(`/api/providers/${unbound.id}`, { method: "DELETE" })).status).toBe(204);
    expect((await request(`/api/providers/${unbound.id}`, { method: "DELETE" })).status).toBe(404);

    const bound = await (await create("Bound")).json();
    await db.insert(capabilityBindings).values({
      capability: "chat",
      providerId: bound.id,
      model: "model",
      vision: false,
    });
    expect((await request(`/api/providers/${bound.id}`, { method: "DELETE" })).status).toBe(409);
  });
});
