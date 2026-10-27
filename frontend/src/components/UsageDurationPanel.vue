<template>
  <section class="usage-panel" data-testid="usage-duration-panel">
    <div class="panel-header">
      <div>
        <h3>使用时长</h3>
        <p class="timezone-note">日期和小时按北京时间解释；包名可留空查询全部应用。</p>
      </div>
      <span v-if="loading" class="count">加载中…</span>
    </div>

    <form class="usage-filters" @submit.prevent="applyDraft">
      <label>包名（可选）<PackageSelect v-model="draft.package_name" input-test-id="usage-package-name" option-test-id="usage-package-option" placeholder="全部包名" :disabled="disabled || loading" :search-packages="searchUsagePackages" allow-free-text /></label>
      <label>开始日期<input data-testid="usage-date-from" v-model="draft.date_from" type="date" :disabled="disabled || loading" /></label>
      <label>开始小时<select data-testid="usage-hour-from" v-model.number="draft.hour_from" :disabled="disabled || loading"><option v-for="hour in hours" :key="`usage-from-${hour}`" :value="hour">{{ hour }}:00</option></select></label>
      <label>结束日期<input data-testid="usage-date-to" v-model="draft.date_to" type="date" :disabled="disabled || loading" /></label>
      <label>结束小时<select data-testid="usage-hour-to" v-model.number="draft.hour_to" :disabled="disabled || loading"><option v-for="hour in hours" :key="`usage-to-${hour}`" :value="hour">{{ hour }}:00</option></select></label>
      <div class="filter-actions"><button data-testid="usage-query" class="primary" type="submit" :disabled="disabled || loading">查询</button><button data-testid="usage-refresh" type="button" :disabled="disabled || loading" @click="refresh">刷新</button></div>
    </form>

    <p v-if="validationError" data-testid="usage-validation-error" class="error">{{ validationError }}</p>
    <p v-if="disabled" data-testid="usage-disabled" class="empty-state">当前不可查询使用时长。</p>
    <p v-if="!disabled" data-testid="usage-applied-scope" class="applied-scope">已生效条件：包名 {{ appliedScope.package_name || "全部包名" }}；{{ appliedScope.date_from }} {{ appliedScope.hour_from }}:00 至 {{ appliedScope.date_to }} {{ appliedScope.hour_to }}:00</p>
    <p v-if="!disabled && error" data-testid="usage-error" class="error">{{ error }} <span class="error-note">已保留上一份成功数据。</span> <button data-testid="usage-retry" type="button" class="ghost" :disabled="loading" @click="retrySummary">重试</button></p>
    <p v-if="!disabled && summary && !summary.items.length && !loading && !error" data-testid="usage-empty" class="empty-state">当前条件下暂无使用时长数据。</p>

    <section v-if="!disabled && summary && summary.items.length" class="panel overview-panel" data-testid="usage-overview-panel">
      <div class="panel-header overview-header">
        <div><h4>包概览</h4><p class="muted">服务端分页结果，统计值保持后端口径。</p></div>
        <label>每页<select data-testid="usage-summary-page-size" :value="summary.page_size" @change="changeSummaryPageSize(Number(($event.target as HTMLSelectElement).value))"><option v-for="size in summaryPageSizes" :key="size" :value="size">{{ size }}</option></select></label>
      </div>
      <div class="table-scroll overview-table-scroll">
        <table class="table usage-summary-table">
          <caption class="sr-only">使用时长包概览</caption>
          <thead><tr><th v-for="header in summaryHeaders" :key="header" data-testid="usage-summary-header">{{ header }}</th></tr></thead>
          <tbody>
            <tr v-for="(item, index) in summary.items" :key="item.package_name" data-testid="usage-summary-row">
              <td>{{ item.package_name }}</td>
              <td>{{ item.device_count }}</td>
              <td :title="item.total_duration_exact_text">{{ item.total_duration_text }}</td>
              <td :title="item.average_duration_exact_text">{{ item.average_duration_text }}</td>
              <td>{{ item.last_report_text }}</td>
              <td><button :data-testid="`usage-view-details-${index}`" class="ghost" type="button" @click="selectPackage(item)">查看详情</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pagination" data-testid="usage-summary-pagination">
        <button data-testid="usage-summary-prev" class="ghost" type="button" :disabled="summary.page <= 1" @click="changeSummaryPage(summary.page - 1)">上一页</button>
        <span>第 {{ summary.page }} / {{ summary.total_pages || 0 }} 页，共 {{ summary.total }} 个包</span>
        <button data-testid="usage-summary-next" class="ghost" type="button" :disabled="summary.total_pages === 0 || summary.page >= summary.total_pages" @click="changeSummaryPage(summary.page + 1)">下一页</button>
      </div>
    </section>

    <section v-if="selectedPackage" class="panel detail-panel" data-testid="usage-device-panel">
      <div class="panel-header">
        <div><h4 data-testid="usage-selected-package">{{ selectedPackage.package_name }}</h4><p class="muted">当前选中包的使用时长详情</p></div>
        <div class="detail-tabs" role="tablist" aria-label="使用时长详情">
          <button data-testid="usage-distribution-tab" type="button" role="tab" :aria-selected="detailTab === 'distribution'" :class="{ active: detailTab === 'distribution' }" @click="selectDetailTab('distribution')">时长分布</button>
          <button data-testid="usage-device-tab" type="button" role="tab" :aria-selected="detailTab === 'devices'" :class="{ active: detailTab === 'devices' }" @click="selectDetailTab('devices')">设备明细</button>
        </div>
      </div>

      <div v-if="detailTab === 'distribution'" data-testid="usage-distribution-panel">
        <div class="table-scroll distribution-table-scroll">
          <table class="table distribution-table">
            <caption class="sr-only">{{ selectedPackage.package_name }} 时长分布</caption>
            <thead><tr><th>区间</th><th>设备数</th><th>占比</th><th>该区间总时长</th></tr></thead>
            <tbody><tr v-for="bucket in selectedPackage.buckets" :key="bucket.key" data-testid="usage-bucket-row"><td>{{ bucket.interval_text }}</td><td>{{ bucket.count_text }}</td><td>{{ bucket.share_text }}</td><td :title="bucket.total_duration_exact_text">{{ bucket.total_duration_text }}</td></tr></tbody>
          </table>
        </div>
      </div>

      <div v-else data-testid="usage-device-content">
        <p v-if="deviceState?.loading && !deviceState.items.length" class="muted">设备明细加载中…</p>
        <p v-else-if="deviceState?.error" class="error">{{ deviceState.error }} <button data-testid="usage-device-retry" type="button" class="ghost" @click="retryDevices">重试</button></p>
        <p v-else-if="deviceState && !deviceState.items.length" class="empty-state">暂无设备明细。</p>
        <div v-else-if="deviceState" class="device-content">
          <p v-if="deviceState.loading" class="muted">正在更新设备明细…</p>
          <div class="table-scroll detail-table-scroll" data-testid="usage-detail-table-scroll">
            <table class="table detail-table">
              <caption class="sr-only">{{ selectedPackage.package_name }} 设备明细</caption>
              <thead><tr><th v-for="header in deviceHeaders" :key="header" data-testid="usage-device-header">{{ header }}</th></tr></thead>
              <tbody><tr v-for="device in deviceState.items" :key="device.device_id" data-testid="usage-device-row"><td>{{ device.device_id }}</td><td>{{ device.device_model || "-" }}</td><td>{{ device.os || "-" }}</td><td :title="device.duration_exact_text">{{ device.duration_text }}</td><td>{{ device.sdk_version || "-" }}</td><td>{{ device.app_version || "-" }}</td><td>{{ device.last_report_text }}</td></tr></tbody>
            </table>
          </div>
          <div class="pagination" data-testid="usage-detail-pagination">
            <label>每页<select data-testid="usage-device-page-size" :value="deviceState.page_size" @change="changeDevicePageSize(Number(($event.target as HTMLSelectElement).value))"><option v-for="size in devicePageSizes" :key="size" :value="size">{{ size }}</option></select></label>
            <button data-testid="usage-device-prev" class="ghost" type="button" :disabled="deviceState.page <= 1" @click="changeDevicePage(deviceState.page - 1)">上一页</button>
            <span>第 {{ deviceState.page }} / {{ deviceState.total_pages || 0 }} 页，共 {{ deviceState.total }} 台</span>
            <button data-testid="usage-device-next" class="ghost" type="button" :disabled="deviceState.total_pages === 0 || deviceState.page >= deviceState.total_pages" @click="changeDevicePage(deviceState.page + 1)">下一页</button>
          </div>
        </div>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from "vue";

import { getUsageDevices, getUsageSummary, searchUsagePackages } from "@/api/usageDurations";
import type { UsageDevice, UsagePage, UsageScope, UsageSummaryItem } from "@/api/usageDurations";
import PackageSelect from "@/components/PackageSelect.vue";
import { defaultRecentThreeDays } from "@/utils/logDateRange";

const props = withDefaults(defineProps<{ disabled?: boolean }>(), { disabled: false });
const hours = Array.from({ length: 24 }, (_, index) => index);
const summaryHeaders = ["包名", "设备数", "总时长", "平均时长", "最后上报", "详情"];
const deviceHeaders = ["设备 ID", "机型", "OS", "最新时长", "SDK 版本", "应用版本", "最后上报"];
const summaryPageSizes = [10, 20, 50];
const devicePageSizes = [10, 20, 50];
const recent = defaultRecentThreeDays();
const draft = reactive({ package_name: "", date_from: recent.date_from, hour_from: recent.hour_from, date_to: recent.date_to, hour_to: recent.hour_to });
const appliedScope = ref<UsageScope>({ date_from: recent.date_from, hour_from: recent.hour_from, date_to: recent.date_to, hour_to: recent.hour_to });
const summary = ref<UsagePage<UsageSummaryItem> | null>(null);
const selectedPackage = ref<UsageSummaryItem | null>(null);
const detailTab = ref<"distribution" | "devices">("distribution");
const deviceState = ref<(UsagePage<UsageDevice> & { loading: boolean; error: string }) | null>(null);
const loading = ref(false);
const error = ref("");
const validationError = ref("");
type SummaryRequest = { scope: UsageScope; page: number; pageSize: number; mode: "query" | "page" | "refresh" };
const failedRequest = ref<SummaryRequest | null>(null);
let disposed = false;
let generation = 0;
let summaryRequestId = 0;
let deviceRequestId = 0;

function unwrap<T>(response: unknown): T {
  let value = response && typeof response === "object" && "data" in response ? (response as { data?: unknown }).data : response;
  if (value && typeof value === "object" && "code" in value && "data" in value) value = (value as { data: unknown }).data;
  return value as T;
}

function scopeKey(scope: UsageScope) { return `${scope.package_name ?? ""}|${scope.date_from}|${scope.hour_from}|${scope.date_to}|${scope.hour_to}`; }
function summaryRequestKey(scope: UsageScope, page: number, pageSize: number, requestGeneration: number) { return `${scopeKey(scope)}|summary|${page}|${pageSize}|${requestGeneration}`; }
function deviceRequestKey(scope: UsageScope, packageName: string, page: number, pageSize: number, requestGeneration: number) { return `${scopeKey(scope)}|${packageName}|devices|${page}|${pageSize}|${requestGeneration}`; }
function validate(scope: UsageScope) {
  if (scope.date_to < scope.date_from) return "结束日期不能早于开始日期。";
  if (scope.date_to === scope.date_from && scope.hour_to < scope.hour_from) return "结束小时不能早于开始小时。";
  const start = Date.UTC(...scope.date_from.split("-").map(Number) as [number, number, number]);
  const end = Date.UTC(...scope.date_to.split("-").map(Number) as [number, number, number]);
  return end - start > 30 * 24 * 60 * 60 * 1000 ? "时间范围不能超过 31 天。" : "";
}
function snapshotDraft(): UsageScope { return { package_name: draft.package_name.trim() || undefined, date_from: draft.date_from, hour_from: draft.hour_from, date_to: draft.date_to, hour_to: draft.hour_to }; }
function resetDetail() { selectedPackage.value = null; deviceState.value = null; detailTab.value = "distribution"; ++deviceRequestId; }

async function loadSummary(scope: UsageScope, page: number, pageSize: number, mode: "query" | "page" | "refresh") {
  const requestId = ++summaryRequestId;
  const requestGeneration = mode === "query" ? ++generation : generation;
  const requestKey = summaryRequestKey(scope, page, pageSize, requestGeneration);
  void requestKey;
  const previousPackage = selectedPackage.value?.package_name;
  loading.value = true;
  error.value = "";
  failedRequest.value = null;
  try {
    const response = await getUsageSummary({ ...scope, page, page_size: pageSize });
    if (disposed || requestId !== summaryRequestId || requestGeneration !== generation) return;
    const data = unwrap<UsagePage<UsageSummaryItem>>(response);
    appliedScope.value = { ...scope };
    summary.value = data;
    failedRequest.value = null;
    if (mode === "refresh" && previousPackage) {
      selectedPackage.value = data.items.find((item) => item.package_name === previousPackage) ?? null;
      ++deviceRequestId;
      deviceState.value = null;
      if (!selectedPackage.value) detailTab.value = "distribution";
    } else {
      resetDetail();
      if (data.items.length === 1) selectedPackage.value = data.items[0];
    }
  } catch (cause) {
    if (!disposed && requestId === summaryRequestId && requestGeneration === generation) {
      error.value = cause instanceof Error ? cause.message : "使用时长读取失败";
      failedRequest.value = { scope: { ...scope }, page, pageSize, mode };
    }
  } finally {
    if (!disposed && requestId === summaryRequestId && requestGeneration === generation) loading.value = false;
  }
}

function applyScope(scope: UsageScope) {
  validationError.value = validate(scope);
  if (validationError.value) return;
  void loadSummary(scope, 1, summary.value?.page_size || 10, "query");
}
function applyDraft() { if (!props.disabled) applyScope(snapshotDraft()); }
function refresh() { if (!props.disabled) void loadSummary({ ...appliedScope.value }, summary.value?.page || 1, summary.value?.page_size || 10, "refresh"); }
function retrySummary() {
  if (props.disabled) return;
  const request = failedRequest.value;
  if (request) void loadSummary({ ...request.scope }, request.page, request.pageSize, request.mode);
  else refresh();
}
function changeSummaryPage(page: number) { if (!summary.value || page < 1 || page > summary.value.total_pages) return; void loadSummary({ ...appliedScope.value }, page, summary.value.page_size, "page"); }
function changeSummaryPageSize(pageSize: number) { if (!summary.value || !summaryPageSizes.includes(pageSize)) return; void loadSummary({ ...appliedScope.value }, 1, pageSize, "page"); }
function selectPackage(item: UsageSummaryItem) { selectedPackage.value = item; detailTab.value = "distribution"; deviceState.value = null; ++deviceRequestId; }

async function loadDevices(page = 1, pageSize = deviceState.value?.page_size || 10) {
  if (!selectedPackage.value) return;
  const requestId = ++deviceRequestId;
  const packageName = selectedPackage.value.package_name;
  const requestGeneration = generation;
  const requestKey = deviceRequestKey(appliedScope.value, packageName, page, pageSize, requestGeneration);
  void requestKey;
  const previous = deviceState.value;
  deviceState.value = { total: previous?.total || 0, total_pages: previous?.total_pages || 0, page, page_size: pageSize, items: previous?.items || [], loading: true, error: "" };
  try {
    const response = await getUsageDevices({ ...appliedScope.value, package_name: packageName, page, page_size: pageSize });
    if (disposed || requestId !== deviceRequestId || requestGeneration !== generation || selectedPackage.value?.package_name !== packageName) return;
    const data = unwrap<UsagePage<UsageDevice>>(response);
    deviceState.value = { ...data, loading: false, error: "" };
  } catch (cause) {
    if (!disposed && requestId === deviceRequestId && requestGeneration === generation && selectedPackage.value?.package_name === packageName) deviceState.value = { ...(deviceState.value || { total: 0, total_pages: 0, page, page_size: pageSize, items: [] }), loading: false, error: cause instanceof Error ? cause.message : "设备明细读取失败" };
  }
}
function selectDetailTab(tab: "distribution" | "devices") { detailTab.value = tab; if (tab === "devices" && !deviceState.value) void loadDevices(); }
function changeDevicePage(page: number) { if (!deviceState.value || page < 1 || page > deviceState.value.total_pages) return; void loadDevices(page, deviceState.value.page_size); }
function changeDevicePageSize(pageSize: number) { if (!devicePageSizes.includes(pageSize)) return; void loadDevices(1, pageSize); }
function retryDevices() { void loadDevices(deviceState.value?.page || 1, deviceState.value?.page_size || 10); }

onMounted(() => { if (!props.disabled) void loadSummary({ ...appliedScope.value }, 1, 10, "query"); });
onBeforeUnmount(() => { disposed = true; ++summaryRequestId; ++deviceRequestId; ++generation; });
</script>

<style scoped>
.usage-panel { display: grid; gap: 16px; min-width: 0; }
.panel, .detail-panel { min-width: 0; }
.panel-header, .usage-filters, .filter-actions, .pagination, .detail-tabs { display: flex; align-items: center; gap: 12px; }
.panel-header { justify-content: space-between; }
.panel-header h3, .panel-header h4 { margin: 0; color: var(--text-primary); }
.timezone-note, .muted { color: var(--text-muted); font-size: 12px; }
.usage-filters { flex-wrap: wrap; align-items: end; --package-select-height: 36px; --package-select-padding: 8px 10px; }
.usage-filters label { display: grid; gap: 6px; color: var(--text-muted); font-size: 12px; }
.usage-filters input, .usage-filters select, .usage-filters button, .detail-tabs button, .pagination select { border: 1px solid var(--border-soft); border-radius: 6px; color: var(--text-primary); background: var(--panel-bg); padding: 8px 10px; }
.usage-filters button, .detail-tabs button, .pagination button { cursor: pointer; }
.usage-filters .primary { background: var(--hover-bg); }
.usage-filters button:disabled, .usage-filters input:disabled, .usage-filters select:disabled, .pagination button:disabled { cursor: not-allowed; opacity: .5; }
.panel { padding: 18px; border: 1px solid var(--border-soft); border-radius: 6px; background: var(--panel-bg); box-shadow: var(--panel-shadow); }
.overview-header { align-items: flex-start; }
.overview-header label, .pagination label { display: inline-flex; align-items: center; gap: 8px; color: var(--text-muted); font-size: 12px; }
.table-scroll { min-width: 0; max-width: 100%; overflow-x: auto; }
.overview-table-scroll { overflow-x: auto; }
.table { width: 100%; border-collapse: collapse; }
.usage-summary-table { min-width: 860px; }
.distribution-table { min-width: 560px; }
.detail-table { min-width: 900px; }
.table th, .table td { padding: 10px; border-bottom: 1px solid var(--border-soft); text-align: left; white-space: nowrap; }
.ghost { border: 1px solid var(--border-soft); border-radius: 6px; color: var(--text-primary); background: transparent; padding: 6px 10px; cursor: pointer; }
.ghost:hover, .detail-tabs button.active { border-color: var(--accent); color: var(--accent); background: var(--hover-bg); }
.detail-tabs button[aria-selected="true"] { border-color: var(--accent); color: var(--accent); }
.pagination { justify-content: flex-end; flex-wrap: wrap; margin-top: 14px; color: var(--text-muted); font-size: 12px; }
.error { color: var(--danger, var(--error-text)); }
.empty-state { color: var(--text-muted); text-align: center; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }
@media (max-width: 720px) {
  .usage-filters { align-items: stretch; }
  .usage-filters > label, .filter-actions { flex: 1 1 100%; }
  .filter-actions { flex-wrap: wrap; }
  .filter-actions button { flex: 1 1 140px; }
  .panel-header { align-items: flex-start; flex-direction: column; }
  .detail-tabs { width: 100%; }
  .detail-tabs button { flex: 1 1 0; }
  .pagination { justify-content: flex-start; }
}
</style>
