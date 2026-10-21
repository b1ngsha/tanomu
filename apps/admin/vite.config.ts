import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    host: "127.0.0.1",
    port: 3000,
    strictPort: true,
    proxy: Object.fromEntries(
      ["/api", "/auth", "/healthz"].map((path) => [path, "http://127.0.0.1:3001"]),
    ),
  },
});
