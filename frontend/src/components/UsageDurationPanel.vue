<template>
  <section class="usage-panel" data-testid="usage-duration-panel">
    <div class="panel-header">
      <div><h3>使用时长</h3><p class="timezone-note">日期和小时按北京时间解释；包名可留空查询全部应用。</p></div>
      <span v-if="loading" class="count">加载中…</span>
    </div>

    <form class="usage-filters" @submit.prevent="applyDraft">
      <label>包名（可选）<input data-testid="usage-package-name" v-model="draft.package_name" type="text" placeholder="全部包名" :disabled="disabled || loading" /></label>
      <label>开始日期<input data-testid="usage-date-from" v-model="draft.date_from" type="date" :disabled="disabled || loading" /></label>
      <label>开始小时<select data-testid="usage-hour-from" v-model.number="draft.hour_from" :disabled="disabled || loading"><option v-for="hour in hours" :key="`usage-from-${hour}`" :value="hour">{{ hour }}:00</option></select></label>
      <label>结束日期<input data-testid="usage-date-to" v-model="draft.date_to" type="date" :disabled="disabled || loading" /></label>
      <label>结束小时<select data-testid="usage-hour-to" v-model.number="draft.hour_to" :disabled="disabled || loading"><option v-for="hour in hours" :key="`usage-to-${hour}`" :value="hour">{{ hour }}:00</option></select></label>
      <div class="filter-actions"><button data-testid="usage-query" class="primary" type="submit" :disabled="disabled || loading" @click.prevent="applyDraft">查询</button><button data-testid="usage-refresh" type="button" :disabled="disabled || loading" @click="refresh">刷新</button></div>
    </form>
    <p v-if="validationError" data-testid="usage-validation-error" class="error">{{ validationError }}</p>
    <p v-if="disabled" data-testid="usage-disabled" class="empty-state">当前不可查询使用时长。</p>
    <p v-else-if="error" data-testid="usage-error" class="error">{{ error }}</p>
    <p v-else-if="!loading && !summary?.items.length" data-testid="usage-empty" class="empty-state">当前条件下暂无使用时长数据。</p>

    <div v-else-if="summary" class="table-scroll usage-table-scroll">
      <table class="table usage-summary-table">
        <caption class="sr-only">使用时长汇总</caption>
        <thead><tr><th>包名</th><th>设备数</th><th>总时长</th><th>平均时长</th><th>≤300 秒</th><th>301–600 秒</th><th>601–899 秒</th><th>≥900 秒</th><th>最后上报</th><th>明细</th></tr></thead>
        <tbody>
          <template v-for="(item, index) in summary.items" :key="`${item.package_name}-${item.device_model}`">
            <tr data-testid="usage-summary-row">
              <td>{{ item.package_name }}</td><td>{{ item.device_count }}</td>
              <td>{{ formatDuration(item.total_duration_s) }}</td><td>{{ formatDuration(item.average_duration_s) }}</td>
              <td v-for="bucket in item.buckets" :key="bucket.key" :data-testid="`usage-bucket-${bucket.key}`">{{ bucket.count }}（{{ formatShare(bucket.share) }}）</td>
              <td>{{ item.last_report_at ?? "-" }}</td>
              <td><button :data-testid="`usage-expand-${index}`" class="ghost" type="button" :aria-expanded="expandedKey === rowKey(item)" @click="toggleRow(item)">{{ expandedKey === rowKey(item) ? "收起" : "展开" }}</button></td>
            </tr>
            <tr v-if="expandedKey === rowKey(item)" data-testid="usage-detail-container"><td colspan="10">
              <p v-if="detailCache[rowKey(item)]?.loading" class="muted">设备明细加载中…</p>
              <p v-else-if="detailCache[rowKey(item)]?.error" class="error">{{ detailCache[rowKey(item)]?.error }}</p>
              <p v-else-if="!detailCache[rowKey(item)]?.items.length" class="empty-state">暂无设备明细。</p>
              <div v-else class="table-scroll usage-detail-scroll">
                <table class="table"><caption class="sr-only">{{ item.package_name }} 设备明细</caption><thead><tr><th>设备 ID</th><th>机型</th><th>最新时长</th><th>SDK 版本</th><th>应用版本 ver</th><th>最后上报</th></tr></thead>
                  <tbody><tr v-for="device in detailCache[rowKey(item)]?.items" :key="device.device_id" data-testid="usage-device-row"><td>{{ device.device_id }}</td><td>{{ device.device_model || "-" }}</td><td>{{ formatDuration(device.duration_s) }}</td><td>{{ device.sdk_version || "-" }}</td><td>{{ device.app_version || "-" }}</td><td>{{ device.last_report_at ?? "-" }}</td></tr></tbody>
                </table>
              </div>
            </td></tr>
          </template>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from "vue";

import { getUsageDevices, getUsageSummary } from "@/api/usageDurations";
import type { UsageDevice, UsageScope, UsageSummaryItem } from "@/api/usageDurations";
import { defaultRecentThreeDays } from "@/utils/logDateRange";

const props = withDefaults(defineProps<{ disabled?: boolean }>(), { disabled: false });
const hours = Array.from({ length: 24 }, (_, index) => index);
const recent = defaultRecentThreeDays();
const draft = reactive({ package_name: "", date_from: recent.date_from, hour_from: recent.hour_from, date_to: recent.date_to, hour_to: recent.hour_to });
const appliedScope = ref<UsageScope>({ date_from: recent.date_from, hour_from: recent.hour_from, date_to: recent.date_to, hour_to: recent.hour_to });
const summary = ref<{ total: number; page: number; page_size: number; items: UsageSummaryItem[] } | null>(null);
const detailCache = ref<Record<string, { loading: boolean; error: string; items: UsageDevice[] }>>({});
const expandedKey = ref<string | null>(null);
const loading = ref(false);
const error = ref("");
const validationError = ref("");
let disposed = false;
let scopeRequestId = 0;
let detailRequestId = 0;

function unwrap<T>(response: unknown): T {
  let value = response && typeof response === "object" && "data" in response ? (response as { data?: unknown }).data : response;
  if (value && typeof value === "object" && "code" in value && "data" in value) value = (value as { data: unknown }).data;
  return value as T;
}

function scopeKey(scope: UsageScope) { return `${scope.package_name ?? ""}|${scope.date_from}|${scope.hour_from}|${scope.date_to}|${scope.hour_to}`; }
function rowKey(item: UsageSummaryItem) { return `${scopeKey(appliedScope.value)}|${item.package_name}`; }
function validate(scope: UsageScope) {
  if (scope.date_to < scope.date_from) return "结束日期不能早于开始日期。";
  if (scope.date_to === scope.date_from && scope.hour_to < scope.hour_from) return "结束小时不能早于开始小时。";
  const start = Date.UTC(...scope.date_from.split("-").map(Number) as [number, number, number]);
  const end = Date.UTC(...scope.date_to.split("-").map(Number) as [number, number, number]);
  return end - start > 30 * 24 * 60 * 60 * 1000 ? "时间范围不能超过 31 天。" : "";
}
function snapshotDraft(): UsageScope { return { package_name: draft.package_name.trim() || undefined, date_from: draft.date_from, hour_from: draft.hour_from, date_to: draft.date_to, hour_to: draft.hour_to }; }

async function load(scope: UsageScope) {
  const requestId = ++scopeRequestId;
  ++detailRequestId;
  expandedKey.value = null;
  detailCache.value = {};
  loading.value = true; error.value = "";
  try {
    const response = await getUsageSummary(scope);
    if (disposed || requestId !== scopeRequestId) return;
    summary.value = unwrap<{ total: number; page: number; page_size: number; items: UsageSummaryItem[] }>(response);
  } catch (cause) {
    if (!disposed && requestId === scopeRequestId) { summary.value = null; error.value = cause instanceof Error ? cause.message : "使用时长读取失败"; }
  } finally {
    if (!disposed && requestId === scopeRequestId) loading.value = false;
  }
}

function applyScope(scope: UsageScope) {
  validationError.value = validate(scope);
  if (validationError.value) return;
  appliedScope.value = scope;
  void load(scope);
}
function applyDraft() { if (!props.disabled) applyScope(snapshotDraft()); }
function refresh() { if (!props.disabled) void load({ ...appliedScope.value }); }

async function loadDetails(item: UsageSummaryItem, key: string) {
  const requestId = ++detailRequestId;
  const scope = { ...appliedScope.value, package_name: item.package_name, page: 1, page_size: 20 };
  detailCache.value[key] = { loading: true, error: "", items: [] };
  try {
    const response = await getUsageDevices(scope);
    if (disposed || requestId !== detailRequestId || key !== expandedKey.value) return;
    detailCache.value[key] = { loading: false, error: "", items: unwrap<{ items: UsageDevice[] }>(response).items };
  } catch (cause) {
    if (!disposed && requestId === detailRequestId && key === expandedKey.value) detailCache.value[key] = { loading: false, error: cause instanceof Error ? cause.message : "设备明细读取失败", items: [] };
  }
}
function toggleRow(item: UsageSummaryItem) {
  const key = rowKey(item);
  if (expandedKey.value === key) { expandedKey.value = null; return; }
  expandedKey.value = key;
  if (!detailCache.value[key]) void loadDetails(item, key);
}
function formatDuration(seconds: number | null) {
  if (seconds == null) return "-";
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${seconds} 秒（${minutes} 分钟${remainder ? ` ${remainder} 秒` : ""}）`;
}
function formatShare(value: number | null) { return value == null ? "-" : `${Math.round(value * 100)}%`; }

onMounted(() => { if (!props.disabled) void load(appliedScope.value); });
onBeforeUnmount(() => { disposed = true; ++scopeRequestId; ++detailRequestId; });
</script>

<style scoped>
.usage-panel { display: grid; gap: 16px; min-width: 0; }
.panel-header, .usage-filters, .filter-actions { display: flex; align-items: center; gap: 12px; }
.panel-header { justify-content: space-between; }
.panel-header h3 { margin: 0; }
.timezone-note, .muted { color: var(--text-secondary); font-size: 12px; }
.usage-filters { flex-wrap: wrap; align-items: end; }
.usage-filters label { display: grid; gap: 6px; color: var(--text-secondary); font-size: 12px; }
.usage-filters input, .usage-filters select, .usage-filters button { border: 1px solid var(--border-soft); border-radius: 8px; color: var(--text-primary); background: rgba(255, 255, 255, .05); padding: 8px 10px; }
.usage-filters button { cursor: pointer; }
.usage-filters .primary { background: rgba(214, 140, 69, .24); }
.usage-filters button:disabled, .usage-filters input:disabled, .usage-filters select:disabled { cursor: not-allowed; opacity: .5; }
.usage-table-scroll, .usage-detail-scroll { overflow: auto; max-height: 420px; }
.usage-detail-scroll { max-height: 240px; }
.table { width: 100%; border-collapse: collapse; min-width: 1180px; }
.table th, .table td { padding: 10px; border-bottom: 1px solid rgba(255, 255, 255, .08); text-align: left; white-space: nowrap; }
.ghost { border: 1px solid var(--border-soft); border-radius: 8px; color: var(--text-primary); background: transparent; padding: 6px 10px; cursor: pointer; }
.error { color: var(--danger, #d9785d); }
.empty-state { color: var(--text-secondary); text-align: center; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }
</style>
