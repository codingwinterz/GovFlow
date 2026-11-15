import { defineConfig } from "vite";

// No React plugin: Vite 8 compiles .jsx with its built-in Oxc transformer (automatic runtime). No fast refresh.
// /api is proxied to the FastAPI backend, so the browser stays same-origin and no CORS is needed.
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
