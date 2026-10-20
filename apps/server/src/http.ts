import { Hono } from "hono";

export function createHttpApp() {
  const app = new Hono();
  app.get("/healthz", (c) => c.text("ok"));
  return app;
}
