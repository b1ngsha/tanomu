import { z } from "zod";
import { http } from "../../lib/http.ts";
import { providerView, type ProviderInput } from "./contracts.ts";

export const providerApi = {
  list: (signal?: AbortSignal) =>
    http
      .get("/api/providers", { signal })
      .json()
      .then((data: unknown) => z.array(providerView).parse(data)),
  save: (id: string | null, input: ProviderInput) => {
    const { apiKey, ...fields } = input;
    // An omitted replacement key preserves the saved credential.
    const json = id && apiKey === "" ? fields : input;
    const response = id
      ? http.patch(`/api/providers/${encodeURIComponent(id)}`, { json })
      : http.post("/api/providers", { json });
    return response.json().then((data: unknown) => providerView.parse(data));
  },
  remove: async (id: string) => {
    await http.delete(`/api/providers/${encodeURIComponent(id)}`);
  },
};
