import react from "@vitejs/plugin-react";
import {defineConfig} from "vite";

// Build the Berg Agents web UI single-page app into ./dist.
//
// `dist/` is gitignored, so it is produced by `npm run build` (and lazily by
// `berg_agents serve --web` when Node is available) rather than committed. The
// React plugin supplies the JSX transform and Fast Refresh for `npm run dev`.
export default defineConfig({
    plugins: [react()],
    server: {
        proxy: {
            // Proxy all API endpoints to the FastAPI backend.
            // Override with VITE_API_BASE_URL or by editing this file.
            "/providers": "http://localhost:8001",
            "/chat": "http://localhost:8001",
            "/capabilities": "http://localhost:8001",
            "/invoke": "http://localhost:8001",
            "/threads": "http://localhost:8001",
        },
    },
    build: {
        outDir: "dist",
        emptyOutDir: true,
    },
});
