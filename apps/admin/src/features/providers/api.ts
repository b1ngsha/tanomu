import { z } from "zod";
import { http } from "../../lib/http.ts";
import { providerView, type ProviderInput, type ProviderPatch } from "./contracts.ts";

export const providerApi = {
  list: (signal?: AbortSignal) =>
    http
      .get("/api/providers", { signal })
      .json()
      .then((data: unknown) => z.array(providerView).parse(data)),
  create: (input: ProviderInput) =>
    http
      .post("/api/providers", { json: input })
      .json()
      .then((data: unknown) => providerView.parse(data)),
  update: (id: string, patch: ProviderPatch) =>
    http
      .patch(`/api/providers/${encodeURIComponent(id)}`, { json: patch })
      .json()
      .then((data: unknown) => providerView.parse(data)),
  remove: async (id: string) => {
    await http.delete(`/api/providers/${encodeURIComponent(id)}`);
  },
};
