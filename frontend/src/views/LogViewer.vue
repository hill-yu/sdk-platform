<template>
  <div class="stack">
    <p v-if="feedback.error" data-testid="error-feedback" class="feedback error">{{ feedback.error }}</p>
    <p v-if="feedback.success" data-testid="success-feedback" class="feedback success">{{ feedback.success }}</p>

    <div class="view-tabs" role="tablist" aria-label="日志视图">
      <button data-testid="analysis-view-tab" type="button" :class="{ active: view === 'analysis' }" @click="switchView('analysis')">解析统计</button>
      <button data-testid="raw-view-tab" type="button" :class="{ active: view === 'raw' }" @click="switchView('raw')">原始日志</button>
    </div>

    <template v-if="view === 'analysis'">
      <section class="panel filters-panel">
        <div class="panel-header">
          <h3>解析统计</h3>
          <button data-testid="configure-columns" class="ghost" type="button" @click="columnSettingsOpen = true">配置指标</button>
        </div>
        <LogAnalysisFilters
          v-model="draftFilters"
          :applied-value="appliedFilters"
          :loading="summaryLoading"
          @query="queryAnalysis"
          @refresh="refreshAnalysis"
          @reset="resetAnalysis"
        />
      </section>

      <section class="panel analysis-panel" data-testid="analysis-view">
        <div class="panel-header"><h3>聚合结果</h3><span class="count">共 {{ summary.total }} 条</span></div>
        <div class="analysis-toolbar">
          <label>排序字段
            <select data-testid="summary-sort-by" v-model="summarySortBy" :disabled="summaryLoading" @change="sortAnalysis">
              <option value="date">日期</option><option value="package_name">包名</option><option value="user_count">用户数</option>
              <option value="flow_count">流程日志数</option><option value="success_rate">成功率</option><option value="average_duration_ms">平均耗时</option>
              <option value="parse_failure_count">解析失败数</option>
            </select>
          </label>
          <button data-testid="summary-sort-order" class="ghost" type="button" :disabled="summaryLoading" @click="toggleSummarySort">{{ summarySortOrder === "desc" ? "降序" : "升序" }}</button>
        </div>
        <div class="table-scroll">
          <table class="table summary-table">
            <thead><tr><th v-for="column in visibleColumns" :key="column">{{ columnLabels[column] ?? column }}</th></tr></thead>
            <tbody>
              <tr v-if="!summary.items.length"><td data-testid="summary-empty" :colspan="Math.max(visibleColumns.length, 1)" class="empty-state">当前条件下没有聚合结果。</td></tr>
              <tr
                v-for="item in summary.items"
                v-else
                :key="`${item.date}-${item.package_name}`"
                data-testid="summary-row"
                class="clickable-row"
                :class="{ selected: selectedSummary === item }"
                @click="selectSummary(item)"
              >
                <td v-for="column in visibleColumns" :key="column">
                  <PackageProfileCell
                    v-if="isProfileColumn(column)"
                    :package-name="item.package_name"
                    :field="profileField(column)"
                    :model-value="profileValue(item, column)"
                    @click.stop
                    @update:model-value="updateSummaryProfile(item.package_name, column, $event)"
                  />
                  <span v-else>{{ formatSummaryValue(item, column) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="pager">
          <button data-testid="summary-previous-page" class="ghost" type="button" :disabled="summary.page <= 1 || summaryLoading" @click="changeSummaryPage(summary.page - 1)">上一页</button>
          <span>第 {{ summary.page }} / {{ summaryTotalPages }} 页</span>
          <button data-testid="summary-next-page" class="ghost" type="button" :disabled="summary.page >= summaryTotalPages || summaryLoading" @click="changeSummaryPage(summary.page + 1)">下一页</button>
        </div>
      </section>

      <section v-if="selectedSummary" class="panel details-panel" data-testid="details-panel">
        <div class="panel-header"><h3>{{ selectedSummary.date }} · {{ selectedSummary.package_name }}</h3><button data-testid="close-details" class="ghost" type="button" @click="closeDetails">关闭</button></div>
        <LogAnalysisDetail
          :items="details.items"
          :total="details.total"
          :page="details.page"
          :page-size="details.page_size"
          :loading="detailsLoading"
          :error="detailsError"
          :selected="selectedDetail"
          :detail="detail"
          @select="selectDetail"
          @page-change="changeDetailsPage"
        />
      </section>

      <div v-if="columnSettingsOpen" class="modal-backdrop" data-testid="column-settings-modal">
        <section class="panel modal-panel" role="dialog" aria-modal="true" aria-label="配置指标">
          <div class="panel-header"><h3>配置指标</h3><button data-testid="close-column-settings" class="ghost" type="button" @click="columnSettingsOpen = false">关闭</button></div>
          <LogColumnSettings
            :available-columns="availableColumns"
            :default-columns="defaultColumns"
            :model-value="visibleColumns"
            :saving="columnSaving"
            :save-error="columnSaveError"
            @save="saveColumns"
          />
        </section>
      </div>
    </template>

    <template v-else>
      <section class="panel filters-panel">
        <div class="filters">
          <select v-model="rawFilters.package_name" data-testid="package-filter" :aria-busy="filterOptionsLoading" @change="changePackageFilter(rawFilters.package_name)">
            <option value="">全部包名</option>
            <option v-for="packageName in filterOptions.package_names" :key="packageName" :value="packageName">{{ packageName }}</option>
          </select>
          <select v-model="rawFilters.sdk_version" data-testid="sdk-version-filter" :disabled="!rawFilters.package_name || filterOptionsLoading">
            <option value="">全部 SDK 版本</option>
            <option v-for="sdkVersion in filterOptions.sdk_versions" :key="sdkVersion" :value="sdkVersion">{{ sdkVersion }}</option>
          </select>
          <select v-model="rawFilters.log_level" data-testid="level-filter"><option value="">全部级别</option><option value="debug">debug</option><option value="info">info</option><option value="warn">warn</option><option value="error">error</option></select>
          <input v-model="rawFilters.device_id" data-testid="device-filter" type="text" placeholder="device_id" />
          <input v-model="rawFilters.date_from" data-testid="date-from-filter" type="date" />
          <input v-model="rawFilters.date_to" data-testid="date-to-filter" type="date" />
          <button data-testid="query-button" class="primary" type="button" @click="loadLogs({ resetPage: true })">查询</button>
          <button data-testid="refresh-button" class="ghost" type="button" @click="loadLogs()">刷新</button>
        </div>
        <p class="timezone-note">日期按北京时间筛选，包名、设备 ID 和日志级别为完全匹配。</p>
        <p v-if="filterOptionsError" data-testid="filter-options-error" class="feedback error">{{ filterOptionsError }}</p>
        <LogExportPanel
          :package-name="rawFilters.package_name"
          :sdk-version="rawFilters.sdk_version"
          :device-id="rawFilters.device_id"
          :log-level="rawFilters.log_level as '' | LogLevel"
          :date-from="rawFilters.date_from"
          :date-to="rawFilters.date_to"
        />
      </section>
      <div class="viewer-grid">
        <section class="panel list-panel">
          <div class="panel-header"><h3>日志列表</h3><span class="count">共 {{ rawResult.total }} 条</span></div>
          <div data-testid="log-list" class="table-scroll">
            <table class="table">
              <thead><tr><th>时间</th><th>级别</th><th>包名</th><th>设备 ID</th><th>SDK 版本</th><th>tag</th><th>message</th></tr></thead>
              <tbody>
                <tr v-if="rawResult.items.length === 0"><td data-testid="empty-state" colspan="7" class="empty-state">当前筛选条件下没有日志。</td></tr>
                <tr v-for="item in rawResult.items" :key="item.id" data-testid="log-row" class="clickable-row" :class="{ selected: selected?.id === item.id }" @click="selected = item">
                  <td>{{ formatBusinessTime(item.server_ts) }}</td>
                  <td><span data-testid="level-tag" class="level-tag" :class="levelClass(item.payload.level)">{{ display(item.payload.level) }}</span></td>
                  <td>{{ display(item.package_name) }}</td><td>{{ display(item.device_id) }}</td><td>{{ display(item.sdk_version) }}</td>
                  <td data-testid="log-tag">{{ display(item.payload.tag) }}</td><td data-testid="log-message" class="message-cell" :title="display(item.payload.message)">{{ display(item.payload.message) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="pager"><button data-testid="previous-page" class="ghost" type="button" :disabled="rawRequestedPage <= 1" @click="changePage(rawRequestedPage - 1)">上一页</button><span>第 {{ rawPage }} / {{ rawTotalPages }} 页</span><button data-testid="next-page" class="ghost" type="button" :disabled="rawRequestedPage >= rawTotalPages" @click="changePage(rawRequestedPage + 1)">下一页</button></div>
        </section>
        <section class="panel detail-panel"><div class="panel-header"><h3>日志详情</h3></div><LogDetail :item="selected" @copy-success="showCopySuccess" @copy-error="showCopyError" /></section>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";

import { getEventFilterOptions, getEvents } from "@/api/dashboard";
import type { EventFilterOptions, EventItem, EventQuery, LogLevel } from "@/api/dashboard";
import { getLogAnalysisColumns, getLogAnalysisDetail, getLogAnalysisDetails, getLogAnalysisSummary, putLogAnalysisColumns } from "@/api/logAnalysis";
import type { DetailKey, DetailsQuery, LogAnalysisColumns, LogAnalysisSummaryItem, LogDecodeItem, SummaryQuery } from "@/api/logAnalysis";
import LogAnalysisDetail from "@/components/LogAnalysisDetail.vue";
import LogAnalysisFilters, { type LogAnalysisFilterValues } from "@/components/LogAnalysisFilters.vue";
import LogColumnSettings from "@/components/LogColumnSettings.vue";
import PackageProfileCell, { type PackageProfileField } from "@/components/PackageProfileCell.vue";
import LogDetail from "@/components/LogDetail.vue";
import LogExportPanel from "@/components/LogExportPanel.vue";
import { formatBusinessTime } from "@/utils/dateTime";
import { beginFeedback, setFeedbackError, setFeedbackSuccess } from "@/utils/feedback";

type AnalysisList = { total: number; page: number; page_size: number; items: LogAnalysisSummaryItem[] };
type DetailList = { total: number; page: number; page_size: number; items: LogDecodeItem[] };
type View = "analysis" | "raw";

const DEFAULT_COLUMNS = ["date", "package_name", "alias", "url", "company", "account", "user_count", "flow_count", "expected_click_count", "actual_click_count", "ad_click_count", "interstitial_presentation_count", "interstitial_click_count", "average_duration_ms", "success_rate", "parse_failure_count"];
const columnLabels: Record<string, string> = { date: "日期", package_name: "包名", alias: "别名", url: "网页 URL", company: "公司", account: "账户", user_count: "用户数", flow_count: "流程日志数", expected_click_count: "计划点击数", actual_click_count: "实际点击数", ad_click_count: "广告区域点击数", interstitial_presentation_count: "插屏展示数", interstitial_click_count: "插屏点击数", average_duration_ms: "平均流程耗时", success_rate: "成功完成率", parse_failure_count: "解析失败数" };
const profileFields: Record<string, PackageProfileField> = { alias: "alias", company: "company", account: "account" };

const view = ref<View>("analysis");
const feedback = reactive({ error: "", success: "" });
const draftFilters = ref<LogAnalysisFilterValues>({ date_from: "", date_to: "", package_name: "", device_id: "", log_level: "" });
const appliedFilters = ref<LogAnalysisFilterValues>({ ...draftFilters.value });
const summary = reactive<AnalysisList>({ total: 0, page: 1, page_size: 20, items: [] });
const details = reactive<DetailList>({ total: 0, page: 1, page_size: 20, items: [] });
const availableColumns = ref<string[]>(DEFAULT_COLUMNS);
const defaultColumns = ref<string[]>(DEFAULT_COLUMNS);
const visibleColumns = ref<string[]>(DEFAULT_COLUMNS);
const selectedSummary = ref<LogAnalysisSummaryItem | null>(null);
const selectedDetail = ref<LogDecodeItem | null>(null);
const detail = ref<LogDecodeItem | null>(null);
const columnSettingsOpen = ref(false);
const summaryLoading = ref(false);
const detailsLoading = ref(false);
const detailsError = ref("");
const columnSaving = ref(false);
const columnSaveError = ref("");
const summarySortBy = ref("date");
const summarySortOrder = ref<"asc" | "desc">("desc");
let summaryRequestSequence = 0;
let columnsRequestSequence = 0;
let detailsRequestSequence = 0;
let detailRequestSequence = 0;

function responseData<T>(response: unknown): T {
  let value = response && typeof response === "object" && "data" in response ? (response as { data?: unknown }).data : response;
  if (value && typeof value === "object" && "code" in value && "data" in value) value = (value as { data: unknown }).data;
  return value as T;
}

function summaryParams(page: number): SummaryQuery {
  return { page, page_size: summary.page_size, sort_by: summarySortBy.value, sort_order: summarySortOrder.value, date_from: appliedFilters.value.date_from || undefined, date_to: appliedFilters.value.date_to || undefined, package_name: appliedFilters.value.package_name || undefined, device_id: appliedFilters.value.device_id || undefined, log_level: appliedFilters.value.log_level || undefined };
}

async function loadSummary(options: { resetPage?: boolean; targetPage?: number } = {}) {
  const targetPage = options.resetPage ? 1 : (options.targetPage ?? summary.page);
  const requestSequence = ++summaryRequestSequence;
  summaryLoading.value = true;
  try {
    const response = await getLogAnalysisSummary(summaryParams(targetPage));
    if (requestSequence !== summaryRequestSequence) return;
    const data = responseData<AnalysisList>(response);
    summary.total = data.total; summary.page = data.page; summary.page_size = data.page_size; summary.items = data.items;
  } catch (error) {
    if (requestSequence !== summaryRequestSequence) return;
    setFeedbackError(feedback, error instanceof Error ? error.message : "聚合查询失败");
  } finally { if (requestSequence === summaryRequestSequence) summaryLoading.value = false; }
}

async function loadColumns() {
  const requestSequence = ++columnsRequestSequence;
  try {
    const response = await getLogAnalysisColumns();
    if (requestSequence !== columnsRequestSequence) return;
    const data = responseData<LogAnalysisColumns>(response);
    availableColumns.value = [...data.available_columns]; defaultColumns.value = [...data.default_columns]; visibleColumns.value = [...data.columns];
  } catch (error) { if (requestSequence === columnsRequestSequence) setFeedbackError(feedback, error instanceof Error ? error.message : "列配置读取失败"); }
}

function loadAnalysisInitial() { void Promise.all([loadColumns(), loadSummary({ resetPage: true })]); }
function queryAnalysis(value: LogAnalysisFilterValues) { appliedFilters.value = { ...value }; void loadSummary({ resetPage: true }); }
function refreshAnalysis() { void loadSummary(); }
function resetAnalysis(value: LogAnalysisFilterValues) { appliedFilters.value = { ...value }; void loadSummary({ resetPage: true }); }
function sortAnalysis() { void loadSummary({ resetPage: true }); }
function toggleSummarySort() { summarySortOrder.value = summarySortOrder.value === "desc" ? "asc" : "desc"; void loadSummary({ resetPage: true }); }

const summaryTotalPages = computed(() => Math.max(1, Math.ceil(summary.total / summary.page_size)));
function changeSummaryPage(page: number) { const bounded = Math.min(summaryTotalPages.value, Math.max(1, page)); if (bounded !== summary.page) void loadSummary({ targetPage: bounded }); }

function detailParams(item: LogAnalysisSummaryItem, page: number): DetailsQuery { return { date: item.date, package_name: item.package_name, page, page_size: details.page_size, device_id: appliedFilters.value.device_id || undefined, log_level: appliedFilters.value.log_level || undefined }; }
async function loadDetails(item: LogAnalysisSummaryItem, targetPage = 1) {
  const requestSequence = ++detailsRequestSequence; detailsLoading.value = true; detailsError.value = "";
  try {
    const response = await getLogAnalysisDetails(detailParams(item, targetPage));
    if (requestSequence !== detailsRequestSequence) return;
    const data = responseData<DetailList>(response); details.total = data.total; details.page = data.page; details.page_size = data.page_size; details.items = data.items;
  } catch (error) { if (requestSequence === detailsRequestSequence) { detailsError.value = error instanceof Error ? error.message : "明细查询失败"; setFeedbackError(feedback, detailsError.value); } }
  finally { if (requestSequence === detailsRequestSequence) detailsLoading.value = false; }
}
function selectSummary(item: LogAnalysisSummaryItem) { selectedSummary.value = item; selectedDetail.value = null; detail.value = null; void loadDetails(item); }
function closeDetails() { selectedSummary.value = null; selectedDetail.value = null; detail.value = null; ++detailsRequestSequence; ++detailRequestSequence; }
function changeDetailsPage(page: number) { if (selectedSummary.value) void loadDetails(selectedSummary.value, page); }

async function selectDetail(item: LogDecodeItem) {
  selectedDetail.value = item; const requestSequence = ++detailRequestSequence; const key: DetailKey = { event_server_ts: item.event_server_ts, record_index: item.record_index };
  try { const response = await getLogAnalysisDetail(item.event_id, key); if (requestSequence === detailRequestSequence) detail.value = responseData<LogDecodeItem>(response); }
  catch (error) { if (requestSequence === detailRequestSequence) setFeedbackError(feedback, error instanceof Error ? error.message : "详情查询失败"); }
}

function isProfileColumn(column: string): boolean { return column in profileFields; }
function profileField(column: string): PackageProfileField { return profileFields[column] ?? "alias"; }
function profileValue(item: LogAnalysisSummaryItem, column: string): string { return item[profileField(column)] ?? ""; }
function updateSummaryProfile(packageName: string, column: string, value: string) { if (isProfileColumn(column)) for (const item of summary.items) if (item.package_name === packageName) item[profileField(column)] = value; }
function formatSummaryValue(item: LogAnalysisSummaryItem, column: string): string {
  if (column === "url") return display(item.primary_url);
  const value = item[column as keyof LogAnalysisSummaryItem];
  if (column === "success_rate" && (value == null || value === "")) return `-（${item.success_sample_count} 个样本）`;
  if (column === "average_duration_ms" && (value == null || value === "")) return `-（${item.duration_sample_count} 个样本）`;
  if (value == null || value === "") return "-";
  if (column === "success_rate") { const percentage = Number(value) * 100; return `${Number.isInteger(percentage) ? percentage : percentage.toFixed(1)}%（${item.success_sample_count} 个样本）`; }
  if (column === "average_duration_ms") return `${value} ms（${item.duration_sample_count} 个样本）`;
  return String(value);
}

async function saveColumns(columns: string[]) {
  columnSaving.value = true; columnSaveError.value = "";
  try { const response = await putLogAnalysisColumns({ columns }); const data = responseData<LogAnalysisColumns>(response); visibleColumns.value = [...(data.columns ?? columns)]; columnSettingsOpen.value = false; }
  catch (error) { columnSaveError.value = error instanceof Error ? error.message : "列配置保存失败"; setFeedbackError(feedback, columnSaveError.value); }
  finally { columnSaving.value = false; }
}

const rawFilters = reactive({ package_name: "", sdk_version: "", device_id: "", log_level: "", date_from: "", date_to: "" });
const filterOptions = reactive<EventFilterOptions>({ package_names: [], sdk_versions: [] });
const filterOptionsError = ref("");
const filterOptionsLoading = ref(false);
let filterOptionsRequestSequence = 0;
const rawResult = reactive({ total: 0, items: [] as EventItem[] });
const rawPage = ref(1); const rawRequestedPage = ref(1); const rawPageSize = 20; const selected = ref<EventItem | null>(null); let rawRequestSequence = 0;
function display(value: unknown): string { return value == null || value === "" ? "-" : String(value); }
function levelClass(value: unknown): string { return typeof value === "string" ? `level-${value}` : "level-unknown"; }
function rawQueryParams(targetPage: number): EventQuery { return { page: targetPage, page_size: rawPageSize, event_type: "log", package_name: rawFilters.package_name || undefined, sdk_version: rawFilters.sdk_version || undefined, device_id: rawFilters.device_id || undefined, log_level: (rawFilters.log_level || undefined) as LogLevel | undefined, date_from: rawFilters.date_from || undefined, date_to: rawFilters.date_to || undefined }; }
async function loadFilterOptions(packageName?: string): Promise<void> {
  const requestSequence = ++filterOptionsRequestSequence;
  filterOptionsLoading.value = true;
  filterOptionsError.value = "";
  try {
    const response = await getEventFilterOptions(packageName || undefined);
    if (requestSequence !== filterOptionsRequestSequence) return;
    const data = responseData<EventFilterOptions>(response);
    filterOptions.package_names = data.package_names;
    filterOptions.sdk_versions = packageName ? data.sdk_versions : [];
    if (rawFilters.sdk_version && !filterOptions.sdk_versions.includes(rawFilters.sdk_version)) rawFilters.sdk_version = "";
  } catch {
    if (requestSequence === filterOptionsRequestSequence) filterOptionsError.value = "包名和 SDK 版本选项加载失败，可继续查看日志并使用其他筛选条件；请刷新重试。";
  } finally {
    if (requestSequence === filterOptionsRequestSequence) filterOptionsLoading.value = false;
  }
}
function changePackageFilter(packageName: string): void {
  rawFilters.package_name = packageName;
  rawFilters.sdk_version = "";
  filterOptions.sdk_versions = [];
  void loadFilterOptions(packageName || undefined);
}
async function loadLogs(options: { resetPage?: boolean; targetPage?: number } = {}): Promise<void> {
  const targetPage = options.resetPage ? 1 : (options.targetPage ?? rawPage.value); rawRequestedPage.value = targetPage; const requestSequence = ++rawRequestSequence; beginFeedback(feedback);
  try { const response = await getEvents(rawQueryParams(targetPage)); if (requestSequence !== rawRequestSequence) return; rawResult.total = response.data.total; rawResult.items = response.data.items; rawPage.value = targetPage; rawRequestedPage.value = targetPage; if (selected.value) selected.value = rawResult.items.find((item) => item.id === selected.value?.id) ?? null; }
  catch (error) { if (requestSequence !== rawRequestSequence) return; rawRequestedPage.value = rawPage.value; setFeedbackError(feedback, error instanceof Error ? error.message : "日志查询失败"); }
}
const rawTotalPages = computed(() => Math.max(1, Math.ceil(rawResult.total / rawPageSize)));
async function changePage(nextPage: number): Promise<void> { const boundedPage = Math.min(rawTotalPages.value, Math.max(1, nextPage)); if (boundedPage !== rawRequestedPage.value) await loadLogs({ targetPage: boundedPage }); }
function switchView(nextView: View) { view.value = nextView; if (nextView === "raw" && rawRequestSequence === 0) { void loadFilterOptions(); void loadLogs(); } }
function showCopySuccess(): void { setFeedbackSuccess(feedback, "extra 复制成功"); }
function showCopyError(message: string): void { setFeedbackError(feedback, message); }
onMounted(loadAnalysisInitial);
</script>

<style scoped>
.stack { display: flex; flex-direction: column; gap: 20px; min-width: 0; min-height: 0; }
.panel { padding: 22px; border: 1px solid var(--border-soft); border-radius: 24px; background: var(--panel-bg); box-shadow: var(--panel-shadow); }
.view-tabs, .filters, .panel-header, .pager, .analysis-toolbar { display: flex; align-items: center; gap: 12px; }
.view-tabs button, .ghost, .primary { border: 1px solid var(--border-soft); border-radius: 12px; color: var(--text-primary); background: rgba(255, 255, 255, .05); padding: 10px 14px; cursor: pointer; }
.view-tabs button.active, .primary { border-color: rgba(214, 140, 69, .5); background: rgba(214, 140, 69, .24); }
.filters { flex-wrap: wrap; }.filters-panel .panel-header, .panel-header { justify-content: space-between; }.panel-header h3 { margin: 0; }.count { color: var(--text-muted); }
.analysis-toolbar { justify-content: flex-end; margin: 14px 0 0; color: var(--text-secondary); font-size: 12px; }.analysis-toolbar label { display: inline-flex; align-items: center; gap: 6px; }
select, input, button { border: 1px solid var(--border-soft); border-radius: 12px; color: var(--text-primary); background: rgba(255, 255, 255, .05); padding: 10px 12px; }
button:disabled, input:disabled, select:disabled { cursor: not-allowed; opacity: .45; }.timezone-note { margin: 12px 0 0; color: var(--text-muted); font-size: 12px; }
.viewer-grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr); gap: 18px; align-items: start; min-width: 0; min-height: 0; }.viewer-grid > *, .panel, .panel-header, .filters, .analysis-toolbar { min-width: 0; }.table-scroll { min-width: 0; max-width: 100%; overflow-x: auto; }
.table { width: 100%; margin-top: 14px; border-collapse: collapse; }.summary-table { min-width: 1200px; }.table th, .table td { padding: 12px 10px; border-bottom: 1px solid rgba(255, 255, 255, .08); text-align: left; white-space: nowrap; }
.clickable-row { cursor: pointer; }.clickable-row.selected { background: rgba(214, 140, 69, .1); }.message-cell { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.level-tag { display: inline-block; padding: 4px 8px; border-radius: 999px; background: rgba(255, 255, 255, .08); }.level-debug { color: #c6cbd3; }.level-info { color: #8cc8ff; }.level-warn { color: #ffd27a; }.level-error { color: #ff9f96; }
.empty-state { color: var(--text-muted); text-align: center; }.pager { justify-content: space-between; margin-top: 16px; }.feedback { margin: 0; padding: 12px 14px; border-radius: 14px; background: rgba(255, 255, 255, .06); }.feedback.error { color: #ffb0a8; background: rgba(209, 89, 89, .18); }.feedback.success { color: #a8e5bd; background: rgba(73, 150, 99, .18); }
.modal-backdrop { position: fixed; inset: 0; z-index: 10; display: grid; place-items: center; padding: 20px; background: rgba(0, 0, 0, .55); }.modal-panel { width: min(760px, 100%); max-height: calc(100dvh - 40px); min-width: 0; overflow: auto; }
@media (max-width: 1200px) { .viewer-grid { grid-template-columns: 1fr; } }
</style>
