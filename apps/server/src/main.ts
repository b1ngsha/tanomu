import { replyToPrivateMessage } from "@tanomu/core";
import { createChatModel } from "./chat-model.ts";
import { loadConfig } from "./config.ts";
import { createConversationStore } from "./conversation-store.ts";
import { createDb, runMigrations } from "./db/client.ts";
import { createFeishu } from "./feishu.ts";

const config = loadConfig();
const db = createDb(config.DATABASE_URL);
await runMigrations(db);

const feishu = createFeishu(config);
const deps = {
  store: createConversationStore(db),
  model: createChatModel(config),
  send: feishu.send,
};

await feishu.listen((message) => replyToPrivateMessage(message, deps));
console.log("tanomu is listening on Feishu");
