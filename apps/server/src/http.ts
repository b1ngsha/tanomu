import { serveStatic } from "@hono/node-server/serve-static";
import { fileURLToPath } from "node:url";
import { Hono } from "hono";
import { deleteCookie, getSignedCookie, setSignedCookie } from "hono/cookie";
import { z } from "zod";
import { providerProtocol } from "./db/schema.ts";
import { ProviderStoreError } from "./provider-store.ts";
import type { ProviderStore } from "./provider-store.ts";

export interface FeishuOAuth {
  authorizeUrl(state: string): string;
  exchange(code: string): Promise<{ openId: string; name: string }>;
}

type HttpDeps = {
  oauth: FeishuOAuth;
  sessionSecret: string;
  providerStore: ProviderStore;
};
const User = z.object({ openId: z.string().min(1), name: z.string().min(1) });
const Session = User.extend({ exp: z.number() });
const State = z.object({ state: z.string(), exp: z.number() });
const ProviderProtocol = z.enum(providerProtocol.enumValues);
const ProviderKey = z.string().refine((value) => value.trim().length > 0);
const ProviderCreate = z.object({
  name: z.string().trim().min(1),
  protocol: ProviderProtocol,
  baseUrl: z.url().refine((value) => ["http:", "https:"].includes(new URL(value).protocol)),
  apiKey: ProviderKey,
});
const ProviderUpdate = ProviderCreate.partial().extend({
  apiKey: z.union([z.literal(""), ProviderKey]).optional(),
});
const ProviderId = z.uuid();
const cookieOptions = { httpOnly: true, sameSite: "Lax", path: "/" } as const;

function parseCookie(value: string | false | undefined): unknown {
  try {
    return value ? JSON.parse(value) : undefined;
  } catch {
    return undefined;
  }
}

function providerError(error: unknown): Response {
  if (error instanceof ProviderStoreError) {
    switch (error.code) {
      case "provider-not-found":
        return Response.json({ error: error.code }, { status: 404 });
      case "duplicate-provider-name":
      case "provider-in-use":
        return Response.json({ error: error.code }, { status: 409 });
    }
  }
  return Response.json({ error: "internal-error" }, { status: 500 });
}

function invalidRequest(): Response {
  return Response.json({ error: "invalid-request" }, { status: 400 });
}

async function jsonBody<T>(request: Request, schema: z.ZodType<T>): Promise<T | Response> {
  try {
    const parsed = schema.safeParse(await request.json());
    return parsed.success ? parsed.data : invalidRequest();
  } catch {
    return invalidRequest();
  }
}

export function createHttpApp({ oauth, sessionSecret, providerStore }: HttpDeps) {
  const app = new Hono<{ Variables: { user: z.infer<typeof User> } }>();
  app.get("/healthz", (c) => c.text("ok"));
  app.get("/auth/feishu/login", async (c) => {
    const state = crypto.randomUUID();
    await setSignedCookie(
      c,
      "tanomu_oauth_state",
      JSON.stringify({ state, exp: Date.now() + 600_000 }),
      sessionSecret,
      { ...cookieOptions, maxAge: 600 },
    );
    return c.redirect(oauth.authorizeUrl(state));
  });
  app.get("/auth/feishu/callback", async (c) => {
    const state = State.safeParse(
      parseCookie(await getSignedCookie(c, sessionSecret, "tanomu_oauth_state")),
    );
    deleteCookie(c, "tanomu_oauth_state", cookieOptions);
    if (
      !state.success ||
      state.data.exp <= Date.now() ||
      state.data.state !== c.req.query("state")
    ) {
      return c.text("Invalid OAuth state", 400);
    }
    const code = c.req.query("code");
    if (!code || c.req.query("error")) return c.text("Feishu sign-in was not completed", 400);
    try {
      const user = User.parse(await oauth.exchange(code));
      await setSignedCookie(
        c,
        "tanomu_session",
        JSON.stringify({ ...user, exp: Date.now() + 604_800_000 }),
        sessionSecret,
        { ...cookieOptions, maxAge: 604800 },
      );
      return c.redirect("/");
    } catch {
      return c.text("Feishu sign-in failed. Please try again.", 502);
    }
  });
  app.post("/auth/logout", (c) => {
    deleteCookie(c, "tanomu_session", cookieOptions);
    return c.body(null, 204);
  });
  app.use("/api/*", async (c, next) => {
    const session = Session.safeParse(
      parseCookie(await getSignedCookie(c, sessionSecret, "tanomu_session")),
    );
    if (!session.success || session.data.exp <= Date.now())
      return c.json({ error: "Unauthorized" }, 401);
    c.set("user", { openId: session.data.openId, name: session.data.name });
    return next();
  });
  app.get("/api/me", (c) => c.json(c.get("user")));
  app.get("/api/providers", async (c) => {
    try {
      return c.json(await providerStore.listProviders());
    } catch (error) {
      return providerError(error);
    }
  });
  app.post("/api/providers", async (c) => {
    const input = await jsonBody(c.req.raw, ProviderCreate);
    if (input instanceof Response) return input;
    try {
      return c.json(await providerStore.createProvider(input), 201);
    } catch (error) {
      return providerError(error);
    }
  });
  app.patch("/api/providers/:id", async (c) => {
    const id = ProviderId.safeParse(c.req.param("id"));
    const input = await jsonBody(c.req.raw, ProviderUpdate);
    if (!id.success || input instanceof Response) return invalidRequest();
    const update = {
      ...(input.name === undefined ? {} : { name: input.name }),
      ...(input.protocol === undefined ? {} : { protocol: input.protocol }),
      ...(input.baseUrl === undefined ? {} : { baseUrl: input.baseUrl }),
      ...(input.apiKey === undefined ? {} : { apiKey: input.apiKey }),
    };
    try {
      return c.json(await providerStore.updateProvider(id.data, update));
    } catch (error) {
      return providerError(error);
    }
  });
  app.delete("/api/providers/:id", async (c) => {
    const id = ProviderId.safeParse(c.req.param("id"));
    if (!id.success) return invalidRequest();
    try {
      await providerStore.deleteProvider(id.data);
      return c.body(null, 204);
    } catch (error) {
      return providerError(error);
    }
  });
  if (process.env.NODE_ENV === "production") {
    const root = fileURLToPath(new URL("../../admin/dist", import.meta.url));
    app.get("/api/*", (c) => c.notFound());
    app.get("/auth/*", (c) => c.notFound());
    app.get("/*", serveStatic({ root }));
    app.get("/*", serveStatic({ path: `${root}/index.html` }));
  }
  return app;
}
