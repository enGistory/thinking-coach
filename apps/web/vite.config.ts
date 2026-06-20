import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";
import { VitePWA } from "vite-plugin-pwa";

const apiProxyTarget = process.env.VITE_DEV_API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "Thinking Coach",
        short_name: "Coach",
        description: "AI voice thinking coach",
        start_url: "/",
        display: "standalone",
        background_color: "#f8fafc",
        theme_color: "#0f766e",
        icons: [
          {
            src: "/pwa-icon.svg",
            sizes: "any",
            type: "image/svg+xml",
            purpose: "any maskable",
          },
        ],
      },
      workbox: {
        navigateFallback: "/index.html",
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "node",
  },
});
