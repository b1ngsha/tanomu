import { serve } from "@hono/node-server";
import {
  createMessageBatcher,
  recordPrivateMessage,
  replyToPrivateMessages,
  type RecordedMessage,
} from "@tanomu/core";
import { createChatModel } from "./chat-model.ts";
import { loadConfig } from "./config.ts";
import { createConversationStore } from "./conversation-store.ts";
import { createDb, runMigrations } from "./db/client.ts";
import { createFeishu } from "./feishu.ts";
import { createFeishuOAuth } from "./feishu-oauth.ts";
import { createHttpApp } from "./http.ts";
import { createKeyCipher } from "./key-cipher.ts";
import { createLlmCallLog } from "./llm-call-log.ts";
import { importChatBinding } from "./provider-store.ts";

const config = loadConfig();
const db = createDb(config.DATABASE_URL);
await runMigrations(db);
await importChatBinding(db, createKeyCipher(config.MASTER_KEY), config);

const feishu = createFeishu(config);
const deps = {
  store: createConversationStore(db),
  llmCallLog: createLlmCallLog(db),
  model: createChatModel(config),
  vision: config.CHAT_MODEL_VISION,
  send: feishu.send,
  downloadImage: feishu.downloadImage,
};

const batcher = createMessageBatcher<RecordedMessage>({
  windowMs: 2_500,
  onFlush: (chatId, items) => replyToPrivateMessages(chatId, items, deps),
});

const http = createHttpApp({
  oauth: createFeishuOAuth(config),
  sessionSecret: config.SESSION_SECRET,
});
serve({ fetch: http.fetch, port: config.HTTP_PORT });

await feishu.listen(async (message) => {
  const recorded = await recordPrivateMessage(message, deps);
  if (recorded) batcher.add(message.chatId, recorded);
});
// The deploy job waits for this line; keep "tanomu is listening" in sync with .github/workflows/ci.yml.
console.log("tanomu is listening on Feishu");
