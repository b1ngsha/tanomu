import { serve } from "@hono/node-server";
import { replyToPrivateMessage } from "@tanomu/core";
import { createChatModel } from "./chat-model.ts";
import { loadConfig } from "./config.ts";
import { createConversationStore } from "./conversation-store.ts";
import { createDb, runMigrations } from "./db/client.ts";
import { createFeishu } from "./feishu.ts";
import { createFeishuOAuth } from "./feishu-oauth.ts";
import { createHttpApp } from "./http.ts";
import { createLlmCallLog } from "./llm-call-log.ts";

const config = loadConfig();
const db = createDb(config.DATABASE_URL);
await runMigrations(db);

const feishu = createFeishu(config);
const deps = {
  store: createConversationStore(db),
  llmCallLog: createLlmCallLog(db),
  model: createChatModel(config),
  send: feishu.send,
};

const http = createHttpApp({
  oauth: createFeishuOAuth(config),
  sessionSecret: config.SESSION_SECRET,
});
serve({ fetch: http.fetch, port: config.HTTP_PORT });

await feishu.listen((message) => replyToPrivateMessage(message, deps));
// The deploy job waits for this line; keep "tanomu is listening" in sync with .github/workflows/ci.yml.
console.log("tanomu is listening on Feishu");
