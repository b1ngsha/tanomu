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
  /** Sends text to the chat and returns the Feishu message id of what was sent. */
  send: (chatId: string, text: string) => Promise<string>;
  llmCallLog: LlmCallLog;
}

const NON_TEXT_REPLY = "这个我暂时看不了，先发文字给我吧。";

/** Calls the model and records the call; recording failures are logged, never thrown. */
async function generateRecorded(
  { model, llmCallLog }: Pick<ReplyDeps, "model" | "llmCallLog">,
  call: Pick<LlmCall, "capability" | "conversationId">,
  request: { prompt: string },
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
        request,
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

/** Handles one message in a Private Conversation end to end: dedupe, generate, send, persist. */
export async function replyToPrivateMessage(
  message: IncomingMessage,
  { store, send, ...deps }: ReplyDeps,
): Promise<void> {
  const recorded = await store.recordIncoming(message);
  if (!recorded) return;

  const text =
    message.text === undefined
      ? NON_TEXT_REPLY
      : await generateRecorded(
          deps,
          { capability: "chat", conversationId: recorded.conversationId },
          { prompt: message.text },
        );

  const feishuMessageId = await send(message.chatId, text);
  await store.recordReply(recorded.conversationId, { text, feishuMessageId });
}
