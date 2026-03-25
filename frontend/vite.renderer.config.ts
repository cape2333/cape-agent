import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    watch: {
      ignored: ["**/out/**"],
    },
  },
  optimizeDeps: {
    exclude: ["bufferutil", "utf-8-validate"],
    entries: ["src/**/*.{ts,tsx,js,jsx}"],
  },
});
