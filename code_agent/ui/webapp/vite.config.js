import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build the Code Agent web UI single-page app into ./dist.
//
// `dist/` is gitignored, so it is produced by `npm run build` (and lazily by
// `code-agent serve --web` when Node is available) rather than committed. The
// React plugin supplies the JSX transform and Fast Refresh for `npm run dev`.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
