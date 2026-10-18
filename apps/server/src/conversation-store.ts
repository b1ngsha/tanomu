import type { ConversationStore } from "@tanomu/core";
import type { Db } from "./db/client.ts";
import { conversations, messages } from "./db/schema.ts";

export function createConversationStore(db: Db): ConversationStore {
  return {
    async recordIncoming(message) {
      return db.transaction(async (tx) => {
        const [conversation] = await tx
          .insert(conversations)
          .values({ kind: "private", feishuChatId: message.chatId })
          // No-op update so RETURNING yields the row even when the conversation already exists.
          .onConflictDoUpdate({
            target: conversations.feishuChatId,
            set: { feishuChatId: message.chatId },
          })
          .returning({ id: conversations.id });
        if (!conversation) throw new Error("conversation upsert returned no row");

        const inserted = await tx
          .insert(messages)
          .values({
            conversationId: conversation.id,
            role: "user",
            feishuMessageId: message.id,
            senderOpenId: message.senderId,
            content: message.text ?? "",
          })
          .onConflictDoNothing({ target: messages.feishuMessageId })
          .returning({ id: messages.id });

        return inserted.length > 0 ? { conversationId: conversation.id } : undefined;
      });
    },

    async recordReply(conversationId, reply) {
      await db.insert(messages).values({
        conversationId,
        role: "assistant",
        feishuMessageId: reply.feishuMessageId,
        content: reply.text,
      });
    },
  };
}
