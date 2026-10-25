import { createAnthropic } from "@ai-sdk/anthropic";
import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { createOpenAI } from "@ai-sdk/openai";
import type { ChatModel } from "@tanomu/core";
import type { LanguageModel } from "ai";
import { eq } from "drizzle-orm";
import type { Db } from "./db/client.ts";
import { capabilityBindings, providers } from "./db/schema.ts";
import type { KeyCipher } from "./key-cipher.ts";

type ProviderOptions = { baseURL: string; apiKey: string };

const byProtocol: Record<
  (typeof providers.$inferSelect)["protocol"],
  (options: ProviderOptions, model: string) => LanguageModel
> = {
  // Relays implement Chat Completions far more often than the Responses API.
  openai: (options, model) => createOpenAI(options).chat(model),
  anthropic: (options, model) => createAnthropic(options)(model),
  google: (options, model) => createGoogleGenerativeAI(options)(model),
};

/** Reads the chat Binding on every call, so a change applies to the next reply without a restart. */
export function createChatModelResolver(db: Db, cipher: KeyCipher): () => Promise<ChatModel> {
  return async function resolveChatModel() {
    const [binding] = await db
      .select({
        protocol: providers.protocol,
        baseUrl: providers.baseUrl,
        apiKey: providers.apiKey,
        model: capabilityBindings.model,
        vision: capabilityBindings.vision,
      })
      .from(capabilityBindings)
      .innerJoin(providers, eq(capabilityBindings.providerId, providers.id))
      .where(eq(capabilityBindings.capability, "chat"));
    if (!binding) throw new Error("chat has no Binding");

    const model = byProtocol[binding.protocol](
      { baseURL: binding.baseUrl, apiKey: cipher.decrypt(binding.apiKey) },
      binding.model,
    );
    return { model, vision: binding.vision };
  };
}
