import { serveStatic } from "@hono/node-server/serve-static";
import { fileURLToPath } from "node:url";
import { Hono } from "hono";
import { deleteCookie, getSignedCookie, setSignedCookie } from "hono/cookie";
import { z } from "zod";

export interface FeishuOAuth {
  authorizeUrl(state: string): string;
  exchange(code: string): Promise<{ openId: string; name: string }>;
}

type HttpDeps = { oauth: FeishuOAuth; sessionSecret: string };
const User = z.object({ openId: z.string().min(1), name: z.string().min(1) });
const Session = User.extend({ exp: z.number() });
const State = z.object({ state: z.string(), exp: z.number() });
const cookieOptions = { httpOnly: true, sameSite: "Lax", path: "/" } as const;

function parseCookie(value: string | false | undefined): unknown {
  try {
    return value ? JSON.parse(value) : undefined;
  } catch {
    return undefined;
  }
}

export function createHttpApp({ oauth, sessionSecret }: HttpDeps) {
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
  if (process.env.NODE_ENV === "production") {
    const root = fileURLToPath(new URL("../../admin/dist", import.meta.url));
    app.get("/api/*", (c) => c.notFound());
    app.get("/auth/*", (c) => c.notFound());
    app.get("/*", serveStatic({ root }));
    app.get("/*", serveStatic({ path: `${root}/index.html` }));
  }
  return app;
}
