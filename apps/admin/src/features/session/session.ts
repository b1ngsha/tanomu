import { queryOptions } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "../../lib/http.ts";

const userView = z.object({ openId: z.string().min(1), name: z.string().min(1) });

export const sessionApi = {
  me: (signal?: AbortSignal) =>
    http
      .get("/api/me", { signal })
      .json()
      .then((data: unknown) => userView.parse(data)),
  logout: async () => {
    await http.post("/auth/logout");
  },
};

export const sessionQueries = {
  user: () => queryOptions({ queryKey: ["user"], queryFn: ({ signal }) => sessionApi.me(signal) }),
};
