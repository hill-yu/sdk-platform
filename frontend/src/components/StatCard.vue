<template>
  <article class="card">
    <p class="label">{{ title }}</p>
    <div class="value-row">
      <strong>{{ value }}</strong>
      <span :class="trendClass">{{ trendText }}</span>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  title: string;
  value: number | string;
  trend: number;
}>();

const trendClass = computed(() => (props.trend >= 0 ? "trend positive" : "trend negative"));
const trendText = computed(() => `${props.trend >= 0 ? "↑" : "↓"} ${Math.abs(props.trend).toFixed(1)}%`);
</script>

<style scoped>
.card {
  padding: 20px;
  border-radius: 20px;
  background: linear-gradient(180deg, rgba(255, 248, 239, 0.06), rgba(255, 255, 255, 0.03));
  border: 1px solid var(--border-soft);
  box-shadow: var(--panel-shadow);
}

.label {
  margin: 0 0 10px;
  color: var(--text-muted);
  font-size: 13px;
}

.value-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

strong {
  font-size: 30px;
}

.trend {
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
}

.positive {
  background: rgba(83, 168, 123, 0.18);
  color: #8fe3b2;
}

.negative {
  background: rgba(209, 89, 89, 0.18);
  color: #ffb0a8;
}
</style>
