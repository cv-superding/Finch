import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/standalone/",
  build: {
    outDir: "../finch/webui/dist/standalone",
    emptyOutDir: true,
    rollupOptions: {
      input: { finch: resolve(process.cwd(), "finch-test.html") },
    },
  },
});
