import { z } from "zod";
import type { Config } from "./config.ts";
import type { FeishuOAuth } from "./http.ts";

const redirectUri = "http://localhost:3000/auth/feishu/callback";
const Token = z.object({ code: z.literal(0), access_token: z.string().min(1) });
const UserInfo = z.object({
  code: z.literal(0),
  data: z.object({ open_id: z.string().min(1), name: z.string().min(1) }),
});

export function createFeishuOAuth(
  config: Pick<Config, "FEISHU_APP_ID" | "FEISHU_APP_SECRET">,
): FeishuOAuth {
  return {
    authorizeUrl(state) {
      const url = new URL("https://accounts.feishu.cn/open-apis/authen/v1/authorize");
      url.search = new URLSearchParams({
        client_id: config.FEISHU_APP_ID,
        response_type: "code",
        redirect_uri: redirectUri,
        state,
      }).toString();
      return url.toString();
    },
    async exchange(code) {
      const tokenResponse = await fetch("https://open.feishu.cn/open-apis/authen/v2/oauth/token", {
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          grant_type: "authorization_code",
          client_id: config.FEISHU_APP_ID,
          client_secret: config.FEISHU_APP_SECRET,
          code,
          redirect_uri: redirectUri,
        }),
        signal: AbortSignal.timeout(10_000),
      });
      if (!tokenResponse.ok) throw new Error("Feishu token exchange failed");
      const token = Token.parse(await tokenResponse.json());
      const userResponse = await fetch("https://open.feishu.cn/open-apis/authen/v1/user_info", {
        headers: { Authorization: `Bearer ${token.access_token}` },
        signal: AbortSignal.timeout(10_000),
      });
      if (!userResponse.ok) throw new Error("Feishu user lookup failed");
      const { data } = UserInfo.parse(await userResponse.json());
      return { openId: data.open_id, name: data.name };
    },
  };
}
