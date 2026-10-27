import { eq } from "drizzle-orm";
import type { Db } from "./db/client.ts";
import { capabilityBindings, providers } from "./db/schema.ts";
import { StoreError } from "./store-error.ts";

interface ChatBinding {
  providerId: string;
  model: string;
  vision: boolean;
}

export interface ChatBindingStore {
  getChatBinding(): Promise<ChatBinding | null>;
  putChatBinding(input: ChatBinding): Promise<ChatBinding>;
}

export function createChatBindingStore(db: Db): ChatBindingStore {
  return {
    async getChatBinding() {
      const [binding] = await db
        .select({
          providerId: capabilityBindings.providerId,
          model: capabilityBindings.model,
          vision: capabilityBindings.vision,
        })
        .from(capabilityBindings)
        .where(eq(capabilityBindings.capability, "chat"));
      return binding ?? null;
    },

    async putChatBinding(input) {
      return db.transaction(async (tx) => {
        const [provider] = await tx
          .select({ id: providers.id })
          .from(providers)
          .where(eq(providers.id, input.providerId))
          .for("key share");
        if (!provider) throw new StoreError("provider-not-found");
        const [binding] = await tx
          .insert(capabilityBindings)
          .values({
            capability: "chat",
            ...input,
          })
          .onConflictDoUpdate({
            target: capabilityBindings.capability,
            set: { ...input, updatedAt: new Date() },
          })
          .returning({
            providerId: capabilityBindings.providerId,
            model: capabilityBindings.model,
            vision: capabilityBindings.vision,
          });
        return binding!;
      });
    },
  };
}
