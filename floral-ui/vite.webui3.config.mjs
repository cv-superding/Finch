import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/webui3/",
  build: {
    outDir: "../finch/webui/dist/webui3",
    emptyOutDir: true,
    rollupOptions: {
      input: { webui3: resolve(process.cwd(), "webui3.html") },
    },
  },
});
