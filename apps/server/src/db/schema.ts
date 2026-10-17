import { pgEnum, pgTable, text, timestamp, uuid } from "drizzle-orm/pg-core";

export const conversationKind = pgEnum("conversation_kind", ["private", "group"]);
export const messageRole = pgEnum("message_role", ["user", "assistant"]);

export const conversations = pgTable("conversations", {
  id: uuid().primaryKey().defaultRandom(),
  kind: conversationKind().notNull(),
  feishuChatId: text().notNull().unique(),
  createdAt: timestamp({ withTimezone: true }).notNull().defaultNow(),
});

export const messages = pgTable("messages", {
  id: uuid().primaryKey().defaultRandom(),
  conversationId: uuid()
    .notNull()
    .references(() => conversations.id),
  role: messageRole().notNull(),
  feishuMessageId: text().notNull().unique(),
  senderOpenId: text(),
  content: text().notNull(),
  createdAt: timestamp({ withTimezone: true }).notNull().defaultNow(),
});
