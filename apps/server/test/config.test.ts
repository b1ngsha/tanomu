import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config.ts";

const env = {
  DATABASE_URL: "postgres://tanomu:tanomu@localhost:54329/tanomu",
  SESSION_SECRET: "s".repeat(32),
  FEISHU_APP_ID: "cli_test",
  FEISHU_APP_SECRET: "secret",
  CHAT_PROVIDER_PROTOCOL: "openai",
  CHAT_PROVIDER_BASE_URL: "https://api.example.com/v1",
  CHAT_PROVIDER_API_KEY: "sk-test",
  CHAT_MODEL: "gpt-test",
  MASTER_KEY: "0123456789abcdef".repeat(4),
};

describe("loadConfig", () => {
  it("accepts a master key of 64 hex chars", () => {
    expect(loadConfig(env).MASTER_KEY).toBe(env.MASTER_KEY);
  });

  it.each([
    ["missing", undefined],
    ["too short", "0123456789abcdef".repeat(2)],
    ["not hex", "z".repeat(64)],
  ])("rejects a master key that is %s", (_, MASTER_KEY) => {
    expect(() => loadConfig({ ...env, MASTER_KEY })).toThrow(/MASTER_KEY/);
  });
});
