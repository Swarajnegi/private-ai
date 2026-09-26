import { defineConfig } from "vite";
export default defineConfig({
  base: "/ui/",
  build: { outDir: "../ui", emptyOutDir: false },
  server: { host: "127.0.0.1" },
});
