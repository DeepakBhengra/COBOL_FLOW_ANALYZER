import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI backend (api/server.py) runs on port 8000 by default.
// Set API_PROXY to point the UI at another backend, e.g. http://127.0.0.1:8001.
const apiTarget = process.env.API_PROXY || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": apiTarget },
  },
});
