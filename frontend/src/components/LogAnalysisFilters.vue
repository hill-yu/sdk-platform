<template>
  <form class="analysis-filters" @submit.prevent="query">
    <div class="filter-grid">
      <label>
        <span>开始日期（北京时间）</span>
        <input
          data-testid="filter-date-from"
          type="date"
          :value="draft.date_from"
          :disabled="disabled || loading"
          @input="updateField('date_from', $event)"
        />
      </label>
      <label>
        <span>结束日期（北京时间）</span>
        <input
          data-testid="filter-date-to"
          type="date"
          :value="draft.date_to"
          :disabled="disabled || loading"
          @input="updateField('date_to', $event)"
        />
      </label>
      <label>
        <span>包名</span>
        <input
          data-testid="filter-package-name"
          type="text"
          :value="draft.package_name"
          :disabled="disabled || loading"
          placeholder="完全匹配"
          @input="updateField('package_name', $event)"
        />
      </label>
      <label>
        <span>设备 ID</span>
        <input
          data-testid="filter-device-id"
          type="text"
          :value="draft.device_id"
          :disabled="disabled || loading"
          placeholder="完全匹配"
          @input="updateField('device_id', $event)"
        />
      </label>
      <label>
        <span>日志级别</span>
        <select
          data-testid="filter-log-level"
          :value="draft.log_level"
          :disabled="disabled || loading"
          @change="updateField('log_level', $event)"
        >
          <option value="">全部</option>
          <option value="debug">debug</option>
          <option value="info">info</option>
          <option value="warn">warn</option>
          <option value="error">error</option>
        </select>
      </label>
    </div>

    <div class="filter-actions">
      <button data-testid="filter-query" type="submit" :disabled="disabled || loading" @click.prevent="query">查询</button>
      <button data-testid="filter-refresh" type="button" :disabled="disabled || loading" @click="refresh">
        刷新
      </button>
      <button data-testid="filter-reset" type="button" :disabled="disabled || loading" @click="reset">
        重置
      </button>
    </div>

    <p class="filter-note">包名、设备 ID 和日志级别均为完全匹配；日期按北京时间解释。</p>
    <div class="effective-conditions" data-testid="effective-conditions">
      <span class="effective-title">当前生效条件</span>
      <span v-if="!activeConditions.length" data-testid="effective-empty">全部</span>
      <span v-for="condition in activeConditions" :key="condition.key" class="condition" data-testid="effective-condition">
        {{ condition.label }}：{{ condition.value }}
      </span>
    </div>
  </form>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from "vue";

import type { LogLevel } from "@/api/logAnalysis";

export interface LogAnalysisFilterValues {
  date_from: string;
  date_to: string;
  package_name: string;
  device_id: string;
  log_level: LogLevel | "";
}

const EMPTY_FILTERS: LogAnalysisFilterValues = {
  date_from: "",
  date_to: "",
  package_name: "",
  device_id: "",
  log_level: "",
};

const props = withDefaults(
  defineProps<{
    modelValue?: Partial<LogAnalysisFilterValues>;
    appliedValue?: Partial<LogAnalysisFilterValues>;
    disabled?: boolean;
    loading?: boolean;
  }>(),
  { modelValue: () => ({}) },
);

const emit = defineEmits<{
  "update:modelValue": [value: LogAnalysisFilterValues];
  query: [value: LogAnalysisFilterValues];
  refresh: [value: LogAnalysisFilterValues];
  reset: [value: LogAnalysisFilterValues];
}>();

const draft = reactive<LogAnalysisFilterValues>({ ...EMPTY_FILTERS });

function normalize(value: Partial<LogAnalysisFilterValues> | undefined): LogAnalysisFilterValues {
  return {
    date_from: value?.date_from ?? "",
    date_to: value?.date_to ?? "",
    package_name: value?.package_name ?? "",
    device_id: value?.device_id ?? "",
    log_level: value?.log_level ?? "",
  };
}

function replaceDraft(value: Partial<LogAnalysisFilterValues> | undefined) {
  Object.assign(draft, normalize(value));
}

replaceDraft(props.modelValue);
watch(() => props.modelValue, replaceDraft, { deep: true });

const activeConditions = computed(() => {
  const applied = normalize(props.appliedValue ?? props.modelValue);
  const conditions = [
    { key: "date_from", label: "开始日期（北京时间）", value: applied.date_from },
    { key: "date_to", label: "结束日期（北京时间）", value: applied.date_to },
    { key: "package_name", label: "包名", value: applied.package_name },
    { key: "device_id", label: "设备 ID", value: applied.device_id },
    { key: "log_level", label: "日志级别", value: applied.log_level },
  ];
  return conditions.filter((condition) => condition.value);
});

function snapshot(): LogAnalysisFilterValues {
  return { ...draft };
}

function updateField(field: keyof LogAnalysisFilterValues, event: Event) {
  const target = event.target as HTMLInputElement | HTMLSelectElement;
  draft[field] = target.value as never;
  emit("update:modelValue", snapshot());
}

function query() {
  emit("query", snapshot());
}

function refresh() {
  emit("refresh", snapshot());
}

function reset() {
  replaceDraft(EMPTY_FILTERS);
  const value = snapshot();
  emit("update:modelValue", value);
  emit("reset", value);
}
</script>

<style scoped>
.analysis-filters { display: grid; gap: 14px; }
.filter-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
label { display: grid; gap: 6px; color: var(--text-secondary); font-size: 12px; }
input, select { width: 100%; box-sizing: border-box; border: 1px solid var(--border-soft); border-radius: 8px; background: rgba(8, 13, 13, .5); color: var(--text-primary); padding: 8px 10px; }
.filter-actions { display: flex; gap: 8px; }
button { border: 1px solid var(--border-soft); border-radius: 8px; background: rgba(8, 13, 13, .5); color: var(--text-primary); padding: 8px 14px; cursor: pointer; }
button:disabled, input:disabled, select:disabled { cursor: not-allowed; opacity: .55; }
.filter-note, .effective-conditions { margin: 0; color: var(--text-secondary); font-size: 12px; }
.effective-conditions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.effective-title { color: var(--text-primary); font-weight: 600; }
.condition { border-radius: 999px; background: rgba(182, 98, 43, .18); padding: 4px 8px; }
</style>
