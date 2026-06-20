import { defineStore } from "pinia";

export const useAppStore = defineStore("app", {
  state: () => ({
    lastHealthStatus: "unknown" as "unknown" | "ok" | "degraded" | "error",
  }),
  actions: {
    setHealthStatus(status: "ok" | "degraded" | "error") {
      this.lastHealthStatus = status;
    },
  },
});
