import { defineConfig } from "vite";

// serve/ui/ is pure build output now (the old hand-written UI is gone), so it
// can be emptied on every build. The hearth serves it at /ui/.
export default defineConfig({
  base: "/ui/",
  build: { outDir: "../ui", emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: { host: "127.0.0.1" },
});
