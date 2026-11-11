import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `npm run dev` proxies /api to the API container, so the UI can be developed with hot reload
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
  build: { chunkSizeWarningLimit: 5000 }, // plotly is big; it is loaded in its own chunk
});
