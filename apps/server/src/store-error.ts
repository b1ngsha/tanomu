export type StoreErrorCode = "provider-not-found" | "duplicate-provider-name" | "provider-in-use";

export class StoreError extends Error {
  readonly code: StoreErrorCode;

  constructor(code: StoreErrorCode) {
    super(code);
    this.code = code;
  }
}
