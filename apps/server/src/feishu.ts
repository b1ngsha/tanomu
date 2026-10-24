import * as lark from "@larksuiteoapi/node-sdk";
import type { IncomingMessage, ReplyDeps } from "@tanomu/core";
import type { Config } from "./config.ts";

export interface Feishu {
  send: (chatId: string, text: string) => Promise<string>;
  downloadImage: ReplyDeps["downloadImage"];
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

    async downloadImage(messageId, imageKey) {
      const res = await client.im.v1.messageResource.get({
        params: { type: "image" },
        path: { message_id: messageId, file_key: imageKey },
      });
      const contentType: unknown = res.headers?.["content-type"];
      return {
        data: Buffer.concat(await res.getReadableStream().toArray()),
        mediaType: typeof contentType === "string" ? contentType : "image",
      };
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
            ...parseContent(message.message_type, message.content),
          }).catch((error: unknown) => console.error("failed to handle message", error));
        },
      });
      await new lark.WSClient(credentials).start({ eventDispatcher: dispatcher });
    },
  };
}

function parseContent(type: string, content: string): Pick<IncomingMessage, "text" | "attachment"> {
  if (type === "text") return { text: stringField(content, "text") };
  if (type === "file" || type === "media") return { text: undefined, attachment: { kind: "file" } };
  if (type === "image") {
    const key = stringField(content, "image_key");
    if (key !== undefined) return { text: undefined, attachment: { kind: "image", key } };
  }
  return { text: undefined };
}

function stringField(content: string, field: string): string | undefined {
  const parsed: unknown = JSON.parse(content);
  const value: unknown =
    typeof parsed === "object" && parsed !== null ? Reflect.get(parsed, field) : undefined;
  return typeof value === "string" ? value : undefined;
}
