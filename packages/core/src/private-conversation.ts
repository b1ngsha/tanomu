import { generateText, type FilePart, type LanguageModel, type TextPart } from "ai";

/** A message a User sent to tanomu, already normalized away from Feishu's wire format. */
export interface IncomingMessage {
  /** Feishu message id; used to drop redelivered events. */
  id: string;
  /** Feishu chat id of the Private Conversation. */
  chatId: string;
  senderId: string;
  /** Undefined when the message isn't plain text (image, file, sticker…). */
  text: string | undefined;
  /** What the message carries besides text; `file` covers files and media tanomu can't read. */
  attachment?: { kind: "image"; key: string } | { kind: "file" };
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

/** One LLM call as sent to and returned by the model, kept for Persona tuning and usage stats. */
export interface LlmCall {
  capability: "chat";
  conversationId: string | undefined;
  /** e.g. "openai.chat"; "gateway" when the model was given as a string id. */
  provider: string;
  model: string;
  /** What was sent: instructions, prompt, messages. */
  request: unknown;
  /** The response messages, or undefined when the call failed. */
  response: unknown;
  inputTokens: number | undefined;
  outputTokens: number | undefined;
  latencyMs: number;
  error: string | undefined;
}

export interface LlmCallLog {
  record(call: LlmCall): Promise<void>;
}

export interface ReplyDeps {
  store: ConversationStore;
  model: LanguageModel;
  /** Whether `model` accepts images; images are declined when false or unset. */
  vision?: boolean;
  /** Sends text to the chat and returns the Feishu message id of what was sent. */
  send: (chatId: string, text: string) => Promise<string>;
  llmCallLog: LlmCallLog;
  /** Downloads an image a User sent, by its Feishu message id and image key. */
  downloadImage: (
    messageId: string,
    imageKey: string,
  ) => Promise<{ data: Uint8Array; mediaType: string }>;
}

const NON_TEXT_REPLY = "这个我暂时看不了，先发文字给我吧。";
const FILE_REPLY = "文件我暂时还读不了，挑重点用文字发我吧。";
const IMAGE_REPLY = "图我现在还看不了，用文字说说？";

function hasImage(messages: IncomingMessage[]): boolean {
  return messages.some((message) => message.attachment?.kind === "image");
}

/** The fixed reply for a batch the model can't take, or undefined when the model should answer. */
function declineFor(messages: IncomingMessage[], vision: boolean): string | undefined {
  if (messages.some((message) => message.attachment?.kind === "file")) return FILE_REPLY;
  if (hasImage(messages)) return vision ? undefined : IMAGE_REPLY;
  if (messages.every((message) => message.text === undefined)) return NON_TEXT_REPLY;
  return undefined;
}

/** An incoming message together with the Private Conversation it was recorded in. */
export interface RecordedMessage {
  message: IncomingMessage;
  conversationId: string;
}

/** What is sent to the model, and how it is logged: images as media type and size, not bytes. */
interface ChatRequest {
  request:
    | { prompt: string }
    | { messages: [{ role: "user"; content: Array<TextPart | FilePart> }] };
  logged: unknown;
}

/** Calls the model and records the call; recording failures are logged, never thrown. */
async function generateRecorded(
  { model, llmCallLog }: Pick<ReplyDeps, "model" | "llmCallLog">,
  call: Pick<LlmCall, "capability" | "conversationId">,
  { request, logged }: ChatRequest,
): Promise<string> {
  const started = performance.now();
  async function record(
    outcome: Pick<LlmCall, "response" | "inputTokens" | "outputTokens" | "error">,
  ) {
    try {
      await llmCallLog.record({
        ...call,
        ...outcome,
        provider: typeof model === "string" ? "gateway" : model.provider,
        model: typeof model === "string" ? model : model.modelId,
        request: logged,
        latencyMs: Math.round(performance.now() - started),
      });
    } catch (error) {
      console.error("failed to record llm call", error);
    }
  }

  let result;
  try {
    result = await generateText({ model, ...request });
  } catch (error) {
    await record({
      response: undefined,
      inputTokens: undefined,
      outputTokens: undefined,
      error: String(error),
    });
    throw error;
  }
  await record({
    response: result.response.messages,
    inputTokens: result.usage.inputTokens,
    outputTokens: result.usage.outputTokens,
    error: undefined,
  });
  return result.text;
}

/** A plain prompt for text-only batches; one multimodal user message, in batch order, otherwise. */
async function chatRequest(
  messages: IncomingMessage[],
  { downloadImage }: Pick<ReplyDeps, "downloadImage">,
): Promise<ChatRequest> {
  if (!hasImage(messages)) {
    const texts = messages
      .map((message) => message.text)
      .filter((text): text is string => text !== undefined);
    const request = { prompt: texts.join("\n") };
    return { request, logged: request };
  }
  const parts = await Promise.all(
    messages.map(async ({ id, text, attachment }) => {
      if (attachment?.kind === "image") {
        const { data, mediaType } = await downloadImage(id, attachment.key);
        const sent: FilePart = { type: "file", mediaType, data: { type: "data", data } };
        return { sent, logged: { type: "file", mediaType, byteLength: data.byteLength } };
      }
      if (text === undefined) return undefined;
      const sent: TextPart = { type: "text", text };
      return { sent, logged: sent };
    }),
  );
  const kept = parts.filter((part) => part !== undefined);
  return {
    request: { messages: [{ role: "user", content: kept.map((part) => part.sent) }] },
    logged: { messages: [{ role: "user", content: kept.map((part) => part.logged) }] },
  };
}

/** Records an incoming message, returning undefined when Feishu redelivers it. */
export async function recordPrivateMessage(
  message: IncomingMessage,
  { store }: Pick<ReplyDeps, "store">,
): Promise<RecordedMessage | undefined> {
  const recorded = await store.recordIncoming(message);
  return recorded ? { message, conversationId: recorded.conversationId } : undefined;
}

/** Replies once to a batch of recorded messages from the same Private Conversation. */
export async function replyToPrivateMessages(
  chatId: string,
  items: RecordedMessage[],
  { store, send, ...deps }: ReplyDeps,
): Promise<void> {
  const conversationId = items[0]?.conversationId;
  if (conversationId === undefined) return;

  const messages = items.map(({ message }) => message);
  const text =
    declineFor(messages, deps.vision ?? false) ??
    (await generateRecorded(
      deps,
      { capability: "chat", conversationId },
      await chatRequest(messages, deps),
    ));

  const feishuMessageId = await send(chatId, text);
  await store.recordReply(conversationId, { text, feishuMessageId });
}

/** Handles one message end to end without batching; the server records and batches instead. */
export async function replyToPrivateMessage(
  message: IncomingMessage,
  deps: ReplyDeps,
): Promise<void> {
  const recorded = await recordPrivateMessage(message, deps);
  if (recorded) await replyToPrivateMessages(message.chatId, [recorded], deps);
}
