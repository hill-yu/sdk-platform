<template>
  <article class="card light">
    <p class="label">{{ title }}</p>
    <div class="value-row">
      <strong>{{ formattedValue }}</strong>
      <span class="trend-wrap"><span class="trend-label">较昨日</span><span :class="trendClass">{{ trendText }}</span></span>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  title: string;
  value: number | string;
  trend: number;
  light?: boolean;
}>();

const trendClass = computed(() => (props.trend >= 0 ? "trend positive" : "trend negative"));
const formattedValue = computed(() => typeof props.value === "number" ? new Intl.NumberFormat("zh-CN").format(props.value) : props.value);
const trendText = computed(() => `${props.trend >= 0 ? "▲" : "▼"} ${Math.abs(props.trend).toFixed(1)}%`);
</script>

<style scoped>
.card {
  padding: 20px;
  border-radius: 6px;
  background: var(--panel-bg);
  border: 1px solid var(--border-soft);
  box-shadow: var(--panel-shadow);
}

.card.light { padding: 18px 22px; border: 0; border-right: 1px solid var(--border-soft); box-shadow: none; }
.card.light:last-child { border-right: 0; }
.card.light .label { color: var(--text-muted); }
.card.light strong { color: var(--text-primary); }
.card.light .trend { padding: 0; border-radius: 0; background: transparent; }
.card.light .trend-wrap { display: inline-flex; align-items: baseline; gap: 8px; white-space: nowrap; }
.card.light .trend-label { color: var(--text-muted); font-size: 13px; }
.card.light .positive { color: var(--success-text); }
.card.light .negative { color: var(--error-text); }

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

.positive { background: var(--success-bg); color: var(--success-text); }
.negative { background: var(--error-bg); color: var(--error-text); }

@media (max-width: 720px) {
  .card.light .value-row { align-items: flex-start; flex-direction: column; gap: 4px; }
  .card.light .trend-wrap { gap: 6px; }
}
</style>
