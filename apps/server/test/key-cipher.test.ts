import { describe, expect, it } from "vitest";
import { createKeyCipher } from "../src/key-cipher.ts";

const masterKey = "0123456789abcdef".repeat(4);

describe("key cipher", () => {
  it("decrypts what it encrypted, without the plaintext in the stored form", () => {
    const cipher = createKeyCipher(masterKey);
    const stored = cipher.encrypt("sk-live-abcdefghijklmnop");
    expect(stored).not.toContain("abcdefghijklmnop");
    expect(cipher.decrypt(stored)).toBe("sk-live-abcdefghijklmnop");
  });

  it("refuses a tampered stored form", () => {
    const cipher = createKeyCipher(masterKey);
    const bytes = Buffer.from(cipher.encrypt("sk-live-abcdefghijklmnop"), "base64");
    const last = bytes.length - 1;
    bytes.writeUInt8(bytes.readUInt8(last) ^ 1, last);
    expect(() => cipher.decrypt(bytes.toString("base64"))).toThrow();
  });

  it("refuses a key encrypted under another master key", () => {
    const stored = createKeyCipher(masterKey).encrypt("sk-live-abcdefghijklmnop");
    const other = createKeyCipher("fedcba9876543210".repeat(4));
    expect(() => other.decrypt(stored)).toThrow();
  });

  it("masks all but the first 2 and last 4 characters", () => {
    const cipher = createKeyCipher(masterKey);
    expect(cipher.mask(cipher.encrypt("sk-abcdefghijklmnop"))).toBe("sk••••mnop");
  });

  it("masks keys under 16 characters entirely", () => {
    const cipher = createKeyCipher(masterKey);
    expect(cipher.mask(cipher.encrypt("sk-abcdefghijkl"))).toBe("••••");
  });
});
