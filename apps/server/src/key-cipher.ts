import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

const ALGORITHM = "aes-256-gcm";
const IV_BYTES = 12;
const TAG_BYTES = 16;

/** Encrypts Provider API keys at rest with the master key from `MASTER_KEY`. */
export interface KeyCipher {
  /** Returns base64 of IV, auth tag, and ciphertext. */
  encrypt(plaintext: string): string;
  /** Throws when the stored form was tampered with or encrypted under another key. */
  decrypt(stored: string): string;
  /** The only form of a key that leaves the server, e.g. `sk••••abcd`. */
  mask(stored: string): string;
}

const MASK = "••••";
const MIN_REVEALED_LENGTH = 16;

/** `masterKey` is 32 bytes as 64 hex chars; `loadConfig` validates it. */
export function createKeyCipher(masterKey: string): KeyCipher {
  const key = Buffer.from(masterKey, "hex");

  function encrypt(plaintext: string): string {
    const iv = randomBytes(IV_BYTES);
    const cipher = createCipheriv(ALGORITHM, key, iv);
    const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
    return Buffer.concat([iv, cipher.getAuthTag(), ciphertext]).toString("base64");
  }

  function decrypt(stored: string): string {
    const bytes = Buffer.from(stored, "base64");
    const iv = bytes.subarray(0, IV_BYTES);
    const tag = bytes.subarray(IV_BYTES, IV_BYTES + TAG_BYTES);
    const decipher = createDecipheriv(ALGORITHM, key, iv);
    decipher.setAuthTag(tag);
    return Buffer.concat([
      decipher.update(bytes.subarray(IV_BYTES + TAG_BYTES)),
      decipher.final(),
    ]).toString("utf8");
  }

  function mask(stored: string): string {
    const plaintext = decrypt(stored);
    if (plaintext.length < MIN_REVEALED_LENGTH) return MASK;
    return `${plaintext.slice(0, 2)}${MASK}${plaintext.slice(-4)}`;
  }

  return { encrypt, decrypt, mask };
}
