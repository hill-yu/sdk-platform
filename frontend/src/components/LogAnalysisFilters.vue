<template>
  <form class="analysis-filters" @submit.prevent="query">
    <div class="filter-grid">
      <label>
        <span>开始日期（北京时间）</span>
        <input data-testid="filter-date-from" type="date" :value="draft.date_from" :disabled="disabled || loading" @input="updateField('date_from', $event)" />
      </label>
      <label>
        <span>开始小时</span>
        <select data-testid="filter-hour-from" :value="draft.hour_from" :disabled="disabled || loading" @change="updateField('hour_from', $event)">
          <option v-for="hour in hours" :key="`from-${hour}`" :value="hour">{{ hour }}:00</option>
        </select>
      </label>
      <label>
        <span>结束日期（北京时间）</span>
        <input data-testid="filter-date-to" type="date" :value="draft.date_to" :disabled="disabled || loading" @input="updateField('date_to', $event)" />
      </label>
      <label>
        <span>结束小时</span>
        <select data-testid="filter-hour-to" :value="draft.hour_to" :disabled="disabled || loading" @change="updateField('hour_to', $event)">
          <option v-for="hour in hours" :key="`to-${hour}`" :value="hour">{{ hour }}:00</option>
        </select>
      </label>
      <label>
        <span>包名（必填）</span>
        <input data-testid="filter-package-name" type="text" :value="draft.package_name" :disabled="disabled || loading" placeholder="完全匹配" @input="updateField('package_name', $event)" />
      </label>
    </div>

    <div class="filter-actions">
      <button data-testid="filter-query-existing" type="submit" :disabled="disabled || loading" @click.prevent="query">查询已有结果</button>
      <button data-testid="filter-refresh" type="button" :disabled="disabled || loading" @click="refresh">刷新</button>
      <button data-testid="filter-reset" type="button" :disabled="disabled || loading" @click="reset">重置</button>
    </div>

    <p class="filter-note">日期和小时按北京时间解释；包名完全匹配，时间范围最长 7 个日历日。</p>
    <p v-if="error" data-testid="filter-error" class="filter-error">{{ error }}</p>
    <div class="effective-conditions" data-testid="effective-conditions">
      <span class="effective-title">当前生效条件</span>
      <span v-for="condition in activeConditions" :key="condition.key" class="condition">{{ condition.label }}：{{ condition.value }}</span>
    </div>
  </form>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";

import { defaultRecentThreeDays } from "@/utils/logDateRange";
import type { LogLevel } from "@/api/dashboard";

export interface LogAnalysisFilterValues {
  package_name: string;
  date_from: string;
  hour_from: number;
  date_to: string;
  hour_to: number;
  /** @deprecated retained for raw-view callers during the migration. */
  device_id?: string;
  /** @deprecated retained for raw-view callers during the migration. */
  log_level?: LogLevel | "";
}

const recent = defaultRecentThreeDays();
const EMPTY_FILTERS: LogAnalysisFilterValues = {
  package_name: "",
  date_from: recent.date_from,
  hour_from: recent.hour_from,
  date_to: recent.date_to,
  hour_to: recent.hour_to,
};

const props = withDefaults(defineProps<{
  modelValue?: Partial<LogAnalysisFilterValues>;
  appliedValue?: Partial<LogAnalysisFilterValues>;
  disabled?: boolean;
  loading?: boolean;
}>(), { modelValue: () => ({}) });

const emit = defineEmits<{
  "update:modelValue": [value: LogAnalysisFilterValues];
  query: [value: LogAnalysisFilterValues];
  refresh: [value: LogAnalysisFilterValues];
  reset: [value: LogAnalysisFilterValues];
}>();

const hours = Array.from({ length: 24 }, (_, index) => index);
const draft = reactive<LogAnalysisFilterValues>({ ...EMPTY_FILTERS });
const error = ref("");

function normalize(value: Partial<LogAnalysisFilterValues> | undefined): LogAnalysisFilterValues {
  return {
    package_name: value?.package_name ?? "",
    date_from: value?.date_from ?? EMPTY_FILTERS.date_from,
    hour_from: value?.hour_from ?? EMPTY_FILTERS.hour_from,
    date_to: value?.date_to ?? EMPTY_FILTERS.date_to,
    hour_to: value?.hour_to ?? EMPTY_FILTERS.hour_to,
  };
}

function replaceDraft(value: Partial<LogAnalysisFilterValues> | undefined) {
  Object.assign(draft, normalize(value));
}

replaceDraft(props.modelValue);
watch(() => props.modelValue, replaceDraft, { deep: true });

const activeConditions = computed(() => {
  const applied = normalize(props.appliedValue ?? props.modelValue);
  return [
    { key: "package_name", label: "包名", value: applied.package_name },
    { key: "date_from", label: "开始", value: `${applied.date_from} ${applied.hour_from}:00` },
    { key: "date_to", label: "结束", value: `${applied.date_to} ${applied.hour_to}:00` },
  ].filter((condition) => condition.key === "package_name" ? condition.value : true);
});

function snapshot(): LogAnalysisFilterValues {
  return { ...draft };
}

function updateField(field: keyof LogAnalysisFilterValues, event: Event) {
  const target = event.target as HTMLInputElement | HTMLSelectElement;
  const value = field === "hour_from" || field === "hour_to" ? Number(target.value) : target.value;
  draft[field] = value as never;
  emit("update:modelValue", snapshot());
}

function calendarDay(value: string): number {
  const [year, month, day] = value.split("-").map(Number);
  return Date.UTC(year, month - 1, day);
}

function validate(): boolean {
  error.value = "";
  if (!draft.package_name.trim()) {
    error.value = "包名为必填条件。";
    return false;
  }
  if (!draft.date_from || !draft.date_to || calendarDay(draft.date_to) < calendarDay(draft.date_from)) {
    error.value = "结束日期不能早于开始日期。";
    return false;
  }
  if (calendarDay(draft.date_to) - calendarDay(draft.date_from) > 6 * 24 * 60 * 60 * 1000) {
    error.value = "时间范围不能超过 7 天。";
    return false;
  }
  if (draft.date_from === draft.date_to && draft.hour_to < draft.hour_from) {
    error.value = "结束小时不能早于开始小时。";
    return false;
  }
  return true;
}

function query() {
  if (validate()) emit("query", snapshot());
}

function refresh() {
  if (validate()) emit("refresh", snapshot());
}

function reset() {
  replaceDraft(EMPTY_FILTERS);
  error.value = "";
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
.filter-note, .filter-error, .effective-conditions { margin: 0; color: var(--text-secondary); font-size: 12px; }
.filter-error { color: var(--danger, #d9785d); }
.effective-conditions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.effective-title { color: var(--text-primary); font-weight: 600; }
.condition { border-radius: 999px; background: rgba(182, 98, 43, .18); padding: 4px 8px; }
</style>
