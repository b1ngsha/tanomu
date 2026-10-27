import "@testing-library/jest-dom/vitest";
import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, vi } from "vitest";
import { createQueryClient } from "../src/lib/query-client.ts";

export const fetchMock = vi.fn();

beforeEach(() => vi.stubGlobal("fetch", fetchMock));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

export function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function createQueryWrapper() {
  const client = createQueryClient();

  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }

  return { client, wrapper: Wrapper };
}

export function renderWithQuery(ui: ReactElement) {
  const { client, wrapper } = createQueryWrapper();

  return { client, ...render(ui, { wrapper }) };
}
