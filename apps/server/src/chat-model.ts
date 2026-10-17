import { createAnthropic } from "@ai-sdk/anthropic";
import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { createOpenAI } from "@ai-sdk/openai";
import type { LanguageModel } from "ai";
import type { Config } from "./config.ts";

type ProviderOptions = { baseURL: string; apiKey: string };

const byProtocol: Record<
  Config["CHAT_PROVIDER_PROTOCOL"],
  (options: ProviderOptions, model: string) => LanguageModel
> = {
  // Relays implement Chat Completions far more often than the Responses API.
  openai: (options, model) => createOpenAI(options).chat(model),
  anthropic: (options, model) => createAnthropic(options)(model),
  google: (options, model) => createGoogleGenerativeAI(options)(model),
};

export function createChatModel(config: Config): LanguageModel {
  return byProtocol[config.CHAT_PROVIDER_PROTOCOL](
    { baseURL: config.CHAT_PROVIDER_BASE_URL, apiKey: config.CHAT_PROVIDER_API_KEY },
    config.CHAT_MODEL,
  );
}
