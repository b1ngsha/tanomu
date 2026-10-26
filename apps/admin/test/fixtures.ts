import type { Provider, ProviderInput } from "../src/features/providers/contracts.ts";

export const provider: Provider = {
  id: "2b1e3b7d-bcb5-44a9-bb15-dbbd10d9fbb3",
  name: "OpenAI",
  protocol: "openai",
  baseUrl: "https://api.openai.com/v1",
  apiKeyMask: "sk-••••",
};

export const providerInput: ProviderInput = {
  name: "OpenAI",
  protocol: "openai",
  baseUrl: "https://api.openai.com/v1",
  apiKey: "secret",
};
