import * as lark from "@larksuiteoapi/node-sdk";
import type { IncomingMessage } from "@tanomu/core";
import type { Config } from "./config.ts";

export interface Feishu {
  send: (chatId: string, text: string) => Promise<string>;
  /** Connects over the long connection and calls `onPrivateMessage` for each User message in a DM. */
  listen: (onPrivateMessage: (message: IncomingMessage) => Promise<void>) => Promise<void>;
}

export function createFeishu(config: Config): Feishu {
  const credentials = { appId: config.FEISHU_APP_ID, appSecret: config.FEISHU_APP_SECRET };
  const client = new lark.Client(credentials);

  return {
    async send(chatId, text) {
      const res = await client.im.v1.message.create({
        params: { receive_id_type: "chat_id" },
        data: { receive_id: chatId, msg_type: "text", content: JSON.stringify({ text }) },
      });
      const id = res.data?.message_id;
      if (!id) throw new Error(`Feishu send failed: ${res.code} ${res.msg}`);
      return id;
    },

    async listen(onPrivateMessage) {
      const dispatcher = new lark.EventDispatcher({}).register({
        "im.message.receive_v1": (event) => {
          const { message, sender } = event;
          if (message.chat_type !== "p2p" || sender.sender_type !== "user") return;
          // Ack the event immediately; Feishu redelivers if the handler is slow.
          onPrivateMessage({
            id: message.message_id,
            chatId: message.chat_id,
            senderId: sender.sender_id?.open_id ?? "",
            text: message.message_type === "text" ? parseText(message.content) : undefined,
          }).catch((error: unknown) => console.error("failed to handle message", error));
        },
      });
      await new lark.WSClient(credentials).start({ eventDispatcher: dispatcher });
    },
  };
}

function parseText(content: string): string | undefined {
  const parsed: unknown = JSON.parse(content);
  if (typeof parsed === "object" && parsed !== null && "text" in parsed) {
    return typeof parsed.text === "string" ? parsed.text : undefined;
  }
  return undefined;
}
