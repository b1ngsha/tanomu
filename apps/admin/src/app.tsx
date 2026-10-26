import { useMutation, useQuery } from "@tanstack/react-query";
import { Button } from "./components/ui/button.tsx";
import { ChatBinding } from "./features/chat-binding/chat-binding-section.tsx";
import { Providers } from "./features/providers/providers-section.tsx";
import { sessionApi, sessionQueries } from "./features/session/session.ts";
import { errorMessage } from "./lib/http.ts";

export function App() {
  const user = useQuery(sessionQueries.user());
  const logout = useMutation({
    mutationFn: sessionApi.logout,
    onSuccess: () => window.location.replace("/auth/feishu/login"),
  });
  const error = logout.error ?? user.error;

  return (
    <div className="mx-auto max-w-5xl px-6 sm:px-10">
      <header className="flex min-h-24 items-center justify-between gap-4 border-b border-border">
        <span className="text-lg font-semibold tracking-tight">
          tanomu <span className="ml-2 text-sm font-normal text-slate-600">管理台</span>
        </span>
        {user.data && (
          <Button variant="outline" disabled={logout.isPending} onClick={() => logout.mutate()}>
            {logout.isPending ? "正在退出…" : "退出登录"}
          </Button>
        )}
      </header>
      <main className="py-16 sm:py-24">
        {user.data ? (
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            你好，{user.data.name}
          </h1>
        ) : (
          !error && <p role="status">正在加载管理台…</p>
        )}
        {error && (
          <p role="alert" className="mt-6 text-red-700">
            {logout.isError ? "退出登录失败，请重试。" : errorMessage(error)}
          </p>
        )}
        {user.data && (
          <>
            <Providers />
            <ChatBinding />
          </>
        )}
      </main>
    </div>
  );
}
