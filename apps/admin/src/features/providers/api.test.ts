// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { provider, providerInput } from "../../../test/fixtures.ts";
import { fetchMock, json } from "../../../test/test-utils.tsx";
import { errorMessage, needsReconciliation } from "../../lib/http.ts";
import { providerApi } from "./api.ts";

describe("Provider API", () => {
  it("loads Providers with same-origin requests and validates their contract", async () => {
    fetchMock.mockResolvedValue(json([provider]));

    await expect(providerApi.list()).resolves.toEqual([provider]);

    expect(fetchMock).toHaveBeenCalledWith(
      expect.objectContaining({ url: "http://localhost:3000/api/providers" }),
      expect.anything(),
    );
  });

  it("omits an empty replacement key but includes a create key", async () => {
    const bodies: unknown[] = [];
    fetchMock.mockImplementation(async (request: Request) => {
      bodies.push(await request.clone().json());
      return json(provider);
    });

    await providerApi.save(provider.id, { ...providerInput, apiKey: "" });

    expect(bodies[0]).not.toHaveProperty("apiKey");

    await providerApi.save(null, providerInput);

    expect(bodies[1]).toMatchObject({ apiKey: "secret" });
  });

  it("maps known API errors without displaying server-provided text", async () => {
    fetchMock.mockResolvedValue(
      json({ error: "duplicate-provider-name", message: "secret upstream detail" }, 409),
    );

    const error = await providerApi.save(null, providerInput).catch((failure: unknown) => failure);

    expect(errorMessage(error)).toBe("Provider 名称已存在，请更换名称。");
    expect(needsReconciliation(error)).toBe(false);
  });

  it("does not replay a failed write and marks its outcome for reconciliation", async () => {
    fetchMock.mockRejectedValue(new TypeError("connection lost"));

    const error = await providerApi.save(null, providerInput).catch((failure: unknown) => failure);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(needsReconciliation(error)).toBe(true);
    expect(errorMessage(error)).toBe("请求失败，请重试或刷新配置。");
  });

  it("rejects malformed responses and never returns an unvalidated secret", async () => {
    fetchMock.mockResolvedValue(json([{ ...provider, apiKey: "secret" }]));

    await expect(providerApi.list()).resolves.toEqual([provider]);

    fetchMock.mockResolvedValue(json({ id: "not-a-uuid" }));

    await expect(providerApi.list()).rejects.toThrow();
  });
});
