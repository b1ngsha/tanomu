// @vitest-environment jsdom
import { useQuery } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { provider, providerInput } from "../../../test/fixtures.ts";
import { createQueryWrapper, fetchMock, json } from "../../../test/test-utils.tsx";
import { providerQueries, useSaveProvider } from "./queries.ts";

describe("Provider queries", () => {
  it("keeps a Provider save pending until its fresh query has reconciled", async () => {
    let finish!: (response: Response) => void;
    const refetch = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    fetchMock
      .mockResolvedValueOnce(json([provider]))
      .mockResolvedValueOnce(json(provider, 201))
      .mockImplementationOnce(() => refetch);
    const { client, wrapper } = createQueryWrapper();
    const { result } = renderHook(
      () => ({ providers: useQuery(providerQueries.list()), save: useSaveProvider() }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.providers.data).toEqual([provider]));

    act(() => result.current.save.mutate({ id: null, input: providerInput }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(result.current.save.isPending).toBe(true);

    await act(async () => finish(json([{ ...provider, name: "Fresh" }])));

    await waitFor(() => expect(result.current.save.isPending).toBe(false));
    expect(client.getQueryData(providerQueries.list().queryKey)).toEqual([
      { ...provider, name: "Fresh" },
    ]);
  });
});
