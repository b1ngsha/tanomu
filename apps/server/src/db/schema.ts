import { sql } from "drizzle-orm";
import {
  boolean,
  integer,
  jsonb,
  pgEnum,
  pgTable,
  text,
  timestamp,
  uniqueIndex,
  uuid,
} from "drizzle-orm/pg-core";

export const conversationKind = pgEnum("conversation_kind", ["private", "group"]);
export const messageRole = pgEnum("message_role", ["user", "assistant"]);
export const providerProtocol = pgEnum("provider_protocol", ["openai", "anthropic", "google"]);

export const providers = pgTable(
  "providers",
  {
    id: uuid().primaryKey().defaultRandom(),
    name: text().notNull(),
    protocol: providerProtocol().notNull(),
    baseUrl: text().notNull(),
    /** Ciphertext with IV and auth tag; see `key-cipher.ts`. */
    apiKey: text().notNull(),
    createdAt: timestamp({ withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp({ withTimezone: true }).notNull().defaultNow(),
  },
  (table) => [uniqueIndex("providers_name_lower_idx").on(sql`lower(${table.name})`)],
);

export const capabilityBindings = pgTable("capability_bindings", {
  /** Only "chat" for now. */
  capability: text().primaryKey(),
  providerId: uuid()
    .notNull()
    .references(() => providers.id, { onDelete: "restrict" }),
  model: text().notNull(),
  vision: boolean().notNull().default(false),
  updatedAt: timestamp({ withTimezone: true }).notNull().defaultNow(),
});

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

export const llmCalls = pgTable("llm_calls", {
  id: uuid().primaryKey().defaultRandom(),
  conversationId: uuid().references(() => conversations.id),
  capability: text().notNull(),
  provider: text().notNull(),
  model: text().notNull(),
  request: jsonb().notNull(),
  response: jsonb(),
  inputTokens: integer(),
  outputTokens: integer(),
  latencyMs: integer().notNull(),
  error: text(),
  createdAt: timestamp({ withTimezone: true }).notNull().defaultNow(),
});
