<script setup lang="ts">
import { onMounted, ref } from "vue";

import { fetchHealth, healthStatusText, type HealthResponse } from "../api/health";
import { useAppStore } from "../stores/app";

const appStore = useAppStore();
const health = ref<HealthResponse | null>(null);
const message = ref(healthStatusText("unknown"));

async function loadHealth() {
  try {
    health.value = await fetchHealth();
    appStore.setHealthStatus(health.value.status);
    message.value = healthStatusText(health.value.status);
  } catch {
    appStore.setHealthStatus("error");
    message.value = healthStatusText("error");
  }
}

onMounted(() => {
  void loadHealth();
});
</script>

<template>
  <main class="shell">
    <section
      class="status-panel"
      aria-labelledby="app-title"
    >
      <p class="eyebrow">
        P00 工程骨架
      </p>
      <h1 id="app-title">
        Thinking Coach
      </h1>
      <p class="status">
        {{ message }}
      </p>
      <dl
        v-if="health"
        class="checks"
      >
        <div
          v-for="(check, name) in health.checks"
          :key="name"
        >
          <dt>
            {{ name }}
          </dt>
          <dd :class="{ ok: check.ok, bad: !check.ok }">
            {{ check.message }}
          </dd>
        </div>
      </dl>
    </section>
  </main>
</template>
