import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Button } from "./components/ui/button.tsx";
import "./index.css";

type User = { openId: string; name: string };

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    async function loadUser() {
      try {
        const response = await fetch("/api/me", { signal: controller.signal });
        if (response.status === 401) {
          window.location.replace("/auth/feishu/login");
          return;
        }
        if (!response.ok) throw new Error("Failed to load User");
        setUser(await response.json());
      } catch {
        if (!controller.signal.aborted) setError("无法加载管理台，请刷新页面重试。");
      }
    }
    void loadUser();
    return () => controller.abort();
  }, []);

  async function signOut() {
    setSigningOut(true);
    setError("");
    try {
      const response = await fetch("/auth/logout", { method: "POST" });
      if (!response.ok) throw new Error("Failed to sign out");
      window.location.replace("/auth/feishu/login");
    } catch {
      setError("退出登录失败，请重试。");
      setSigningOut(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-6 sm:px-10">
      <header className="flex min-h-24 items-center justify-between gap-4 border-b border-border">
        <span className="text-lg font-semibold tracking-tight">
          tanomu <span className="ml-2 text-sm font-normal text-slate-600">管理台</span>
        </span>
        {user && (
          <Button variant="outline" disabled={signingOut} onClick={() => void signOut()}>
            {signingOut ? "正在退出…" : "退出登录"}
          </Button>
        )}
      </header>
      <main className="py-16 sm:py-24">
        {user ? (
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">你好，{user.name}</h1>
        ) : (
          !error && <p role="status">正在加载管理台…</p>
        )}
        {error && (
          <p role="alert" className="mt-6 text-red-700">
            {error}
          </p>
        )}
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
