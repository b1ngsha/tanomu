import ky from "ky";
import { z } from "zod";
import {
  chatBinding,
  providerView,
  userView,
  type Binding,
  type ProviderInput,
} from "./contracts.ts";

// Query owns retries. Writes must never be replayed by the transport.
const http = ky.create({ baseUrl: window.location.origin, retry: 0, timeout: 15_000 });

export const api = {
  me: (signal?: AbortSignal) =>
    http
      .get("/api/me", { signal })
      .json()
      .then((data: unknown) => userView.parse(data)),
  providers: (signal?: AbortSignal) =>
    http
      .get("/api/providers", { signal })
      .json()
      .then((data: unknown) => z.array(providerView).parse(data)),
  capabilities: (signal?: AbortSignal) =>
    http
      .get("/api/capabilities", { signal })
      .json()
      .then((data: unknown) => z.object({ chat: chatBinding.nullable() }).parse(data)),
  saveProvider: (id: string | null, input: ProviderInput) => {
    const { apiKey, ...fields } = input;
    // An omitted replacement key preserves the saved credential.
    const json = id && apiKey === "" ? fields : input;
    const response = id
      ? http.patch(`/api/providers/${encodeURIComponent(id)}`, { json })
      : http.post("/api/providers", { json });
    return response.json().then((data: unknown) => providerView.parse(data));
  },
  removeProvider: async (id: string) => {
    await http.delete(`/api/providers/${encodeURIComponent(id)}`);
  },
  saveBinding: (json: Binding) =>
    http
      .put("/api/capabilities/chat", { json })
      .json()
      .then((data: unknown) => chatBinding.parse(data)),
  logout: async () => {
    await http.post("/auth/logout");
  },
};
