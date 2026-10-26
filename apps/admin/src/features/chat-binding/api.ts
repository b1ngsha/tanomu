import { z } from "zod";
import { http } from "../../lib/http.ts";
import { chatBinding, type Binding } from "./contracts.ts";

const capabilitiesView = z.object({ chat: chatBinding.nullable() });

export const chatBindingApi = {
  get: (signal?: AbortSignal) =>
    http
      .get("/api/capabilities", { signal })
      .json()
      .then((data: unknown) => capabilitiesView.parse(data)),
  save: (json: Binding) =>
    http
      .put("/api/capabilities/chat", { json })
      .json()
      .then((data: unknown) => chatBinding.parse(data)),
};
