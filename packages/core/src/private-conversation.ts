import { generateText, type LanguageModel } from "ai";

/** A message a User sent to tanomu, already normalized away from Feishu's wire format. */
export interface IncomingMessage {
  /** Feishu message id; used to drop redelivered events. */
  id: string;
  /** Feishu chat id of the Private Conversation. */
  chatId: string;
  senderId: string;
  /** Undefined when the message isn't plain text (image, file, sticker…). */
  text: string | undefined;
}

export interface ConversationStore {
  /**
   * Persists an incoming message in its Private Conversation.
   * Returns `undefined` if this message id was already recorded (a redelivery).
   */
  recordIncoming(message: IncomingMessage): Promise<{ conversationId: string } | undefined>;
  recordReply(
    conversationId: string,
    reply: { text: string; feishuMessageId: string },
  ): Promise<void>;
}

export interface ReplyDeps {
  store: ConversationStore;
  model: LanguageModel;
  /** Sends text to the chat and returns the Feishu message id of what was sent. */
  send: (chatId: string, text: string) => Promise<string>;
}

const NON_TEXT_REPLY = "这个我暂时看不了，先发文字给我吧。";

/** Handles one message in a Private Conversation end to end: dedupe, generate, send, persist. */
export async function replyToPrivateMessage(
  message: IncomingMessage,
  { store, model, send }: ReplyDeps,
): Promise<void> {
  const recorded = await store.recordIncoming(message);
  if (!recorded) return;

  const text =
    message.text === undefined
      ? NON_TEXT_REPLY
      : (await generateText({ model, prompt: message.text })).text;

  const feishuMessageId = await send(message.chatId, text);
  await store.recordReply(recorded.conversationId, { text, feishuMessageId });
}
