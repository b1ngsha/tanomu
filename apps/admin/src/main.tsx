import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app.tsx";
import "./index.css";
import { createQueryClient } from "./lib/query-client.ts";

function Root() {
  const [client] = useState(createQueryClient);

  return (
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
