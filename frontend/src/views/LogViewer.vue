<template>
  <div class="stack">
    <p v-if="feedback.error" data-testid="error-feedback" class="feedback error">{{ feedback.error }}</p>
    <p v-if="feedback.success" data-testid="success-feedback" class="feedback success">{{ feedback.success }}</p>

    <div class="view-tabs" role="tablist" aria-label="日志视图">
      <button data-testid="analysis-view-tab" type="button" :class="{ active: view === 'analysis' }" @click="switchView('analysis')">解析统计</button>
      <button data-testid="raw-view-tab" type="button" :class="{ active: view === 'raw' }" @click="switchView('raw')">原始日志</button>
      <button data-testid="usage-view-tab" type="button" :class="{ active: view === 'usage' }" @click="switchView('usage')">使用时长</button>
    </div>

    <template v-if="view === 'analysis'">
      <section class="panel filters-panel">
        <div class="panel-header">
          <h3>解析统计</h3>
        </div>
        <LogAnalysisFilters
          v-model="draftFilters"
          :applied-value="appliedFilters"
          :loading="false"
          @query="queryAnalysis"
          @refresh="refreshAnalysis"
          @reset="resetAnalysis"
        />
      </section>

      <LogParseTaskPanel
        :draft-scope="analysisScopeFromFilters(draftFilters)"
        :applied-scope="metricScope"
        :job="parseJob"
        :starting="parseStarting"
        :cancelling="parseCancelling"
        @request-parse="requestParse"
        @request-cancel="requestCancel"
      />
      <LogMetricsPanel :scope="metricScope" :job="parseJob" :profile="packageProfile" :visible-columns="visibleColumns" @failure-select="openFailureDrawer" @configure-columns="columnSettingsOpen = true" @profile-update="updatePackageProfile" @profile-error="showProfileError" />
      <LogFailureDrawer :open="failureDrawerOpen" :items="failureItems" :loading="failureLoading" :error="failureError" @close="closeFailureDrawer" />

      <div v-if="columnSettingsOpen" class="modal-backdrop" data-testid="column-settings-modal">
        <section class="panel modal-panel" role="dialog" aria-modal="true" aria-label="配置指标">
          <div class="panel-header"><h3>配置指标</h3><button data-testid="close-column-settings" class="ghost" type="button" @click="columnSettingsOpen = false">关闭</button></div>
          <LogColumnSettings
            :available-columns="availableColumns"
            :default-columns="defaultColumns"
            :model-value="visibleColumns"
            :mapped-columns="FORMAL_COLUMN_LIST"
            :saving="columnSaving"
            :save-error="columnSaveError"
            @save="saveColumns"
          />
        </section>
      </div>
    </template>

    <template v-else-if="view === 'raw'">
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
          <select v-model="rawFilters.hour_from" data-testid="hour-from-filter">
            <option value="">开始小时</option>
            <option v-for="option in hourOptions" :key="`from-${option.value}`" :value="option.value">{{ option.label }}</option>
          </select>
          <input v-model="rawFilters.date_to" data-testid="date-to-filter" type="date" />
          <select v-model="rawFilters.hour_to" data-testid="hour-to-filter">
            <option value="">结束小时</option>
            <option v-for="option in hourOptions" :key="`to-${option.value}`" :value="option.value">{{ option.label }}</option>
          </select>
          <button data-testid="query-button" class="primary" type="button" @click="queryRaw">查询</button>
          <button data-testid="refresh-button" class="ghost" type="button" @click="loadLogs()">刷新</button>
          <button data-testid="reset-button" class="ghost" type="button" @click="resetRaw">重置</button>
        </div>
        <p class="timezone-note">日期按北京时间筛选，包名、设备 ID 和日志级别为完全匹配。</p>
        <p v-if="filterOptionsError" data-testid="filter-options-error" class="feedback error">{{ filterOptionsError }}</p>
        <LogExportPanel
          :package-name="appliedRawFilters.package_name"
          :sdk-version="appliedRawFilters.sdk_version"
          :device-id="appliedRawFilters.device_id"
          :log-level="appliedRawFilters.log_level as '' | LogLevel"
          :date-from="appliedRawFilters.date_from"
          :hour-from="appliedRawFilters.hour_from"
          :date-to="appliedRawFilters.date_to"
          :hour-to="appliedRawFilters.hour_to"
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
    <section v-else class="panel usage-placeholder" data-testid="usage-view">
      <UsageDurationPanel />
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";

import { getEventFilterOptions, getEvents } from "@/api/dashboard";
import type { EventFilterOptions, EventItem, EventQuery, LogLevel } from "@/api/dashboard";
import { cancelParseJob, getLatestParseJob, getMetricFailures, getParseJob, postParseJob } from "@/api/logMetrics";
import type { FailureBreakdownItem, LogMetricScope, ParseJob } from "@/api/logMetrics";
import { getLogAnalysisColumns, getPackageProfile, putLogAnalysisColumns } from "@/api/logAnalysis";
import { FORMAL_METRIC_COLUMN_MAPPING } from "@/api/logAnalysis";
import type { LogAnalysisColumns, PackageProfile } from "@/api/logAnalysis";
import LogAnalysisFilters, { type LogAnalysisFilterValues } from "@/components/LogAnalysisFilters.vue";
import LogColumnSettings from "@/components/LogColumnSettings.vue";
import LogFailureDrawer from "@/components/LogFailureDrawer.vue";
import LogDetail from "@/components/LogDetail.vue";
import LogExportPanel from "@/components/LogExportPanel.vue";
import LogMetricsPanel from "@/components/LogMetricsPanel.vue";
import LogParseTaskPanel from "@/components/LogParseTaskPanel.vue";
import UsageDurationPanel from "@/components/UsageDurationPanel.vue";
import { formatBusinessTime } from "@/utils/dateTime";
import { beginFeedback, setFeedbackError, setFeedbackSuccess } from "@/utils/feedback";
import { defaultRecentThreeDays } from "@/utils/logDateRange";
import { analysisScopeUtcRange, validateAnalysisScope } from "@/utils/logAnalysisScope";

type View = "analysis" | "raw" | "usage";

// The legacy columns endpoint remains unchanged. The formal view maps only
// these IDs to a visible profile/card/table; other historical IDs round-trip
// through settings but are explicitly marked as not rendered.
const DEFAULT_COLUMNS = ["date", "package_name", "alias", "company", "account", "url", "expected_click_count", "actual_click_count", "ad_click_count", "interstitial_presentation_count", "interstitial_click_count", "parse_failure_count"];
const FORMAL_COLUMN_IDS = new Set(["date", "package_name", ...Object.keys(FORMAL_METRIC_COLUMN_MAPPING)]);
const FORMAL_COLUMN_LIST = [...FORMAL_COLUMN_IDS];

const view = ref<View>("analysis");
const feedback = reactive({ error: "", success: "" });
const recentAnalysisRange = defaultRecentThreeDays();
const draftFilters = ref<LogAnalysisFilterValues>({ date_from: recentAnalysisRange.date_from, hour_from: recentAnalysisRange.hour_from, date_to: recentAnalysisRange.date_to, hour_to: recentAnalysisRange.hour_to, package_name: "", device_id: "", log_level: "" });
const appliedFilters = ref<LogAnalysisFilterValues>({ ...draftFilters.value });
const metricScope = ref<LogMetricScope>({ package_name: "", date_from: recentAnalysisRange.date_from, hour_from: recentAnalysisRange.hour_from, date_to: recentAnalysisRange.date_to, hour_to: recentAnalysisRange.hour_to });
const parseJob = ref<ParseJob | null>(null);
const parseStarting = ref(false);
const parseCancelling = ref(false);
const packageProfile = ref<PackageProfile | null>(null);
const failureDrawerOpen = ref(false);
const failureItems = ref<FailureBreakdownItem[]>([]);
const failureLoading = ref(false);
const failureError = ref("");
const availableColumns = ref<string[]>(DEFAULT_COLUMNS);
const defaultColumns = ref<string[]>(DEFAULT_COLUMNS);
const visibleColumns = ref<string[]>(DEFAULT_COLUMNS);
const columnSettingsOpen = ref(false);
const columnSaving = ref(false);
const columnSaveError = ref("");
let columnsRequestSequence = 0;
let profileRequestSequence = 0;
let failureRequestSequence = 0;
let parseRequestSequence = 0;
let parsePollTimer: ReturnType<typeof setTimeout> | null = null;

function responseData<T>(response: unknown): T {
  let value = response && typeof response === "object" && "data" in response ? (response as { data?: unknown }).data : response;
  if (value && typeof value === "object" && "code" in value && "data" in value) value = (value as { data: unknown }).data;
  return value as T;
}

async function loadColumns() {
  const requestSequence = ++columnsRequestSequence;
  try {
    const response = await getLogAnalysisColumns();
    if (requestSequence !== columnsRequestSequence) return;
    const data = responseData<LogAnalysisColumns>(response);
    availableColumns.value = [...new Set([...data.available_columns, ...data.default_columns, ...data.columns])];
    defaultColumns.value = [...data.default_columns];
    visibleColumns.value = [...data.columns];
  } catch (error) { if (requestSequence === columnsRequestSequence) setFeedbackError(feedback, error instanceof Error ? error.message : "列配置读取失败"); }
}

async function loadPackageProfile(packageName: string) {
  const requestSequence = ++profileRequestSequence;
  packageProfile.value = null;
  if (!packageName) return;
  try {
    const response = await getPackageProfile(packageName);
    if (requestSequence === profileRequestSequence) packageProfile.value = responseData<PackageProfile>(response);
  } catch (error) {
    if (requestSequence === profileRequestSequence) setFeedbackError(feedback, error instanceof Error ? error.message : "包资料读取失败");
  }
}

function loadAnalysisInitial() { void loadColumns(); }
function analysisScopeFromFilters(value: LogAnalysisFilterValues): LogMetricScope {
  return { package_name: value.package_name, date_from: value.date_from, hour_from: value.hour_from, date_to: value.date_to, hour_to: value.hour_to };
}
async function loadLatestParseJob(scope: LogMetricScope) {
  const requestSequence = ++parseRequestSequence;
  clearParsePoll();
  parseJob.value = null;
  if (!scope.package_name) { parseJob.value = null; return; }
  try {
    const response = await getLatestParseJob(scope);
    if (requestSequence !== parseRequestSequence) return;
    const candidate = responseData<ParseJob | null>(response);
    parseJob.value = candidate && latestJobMatchesScope(candidate, scope) ? candidate : null;
    scheduleParsePoll(scope, requestSequence);
  } catch (error) {
    if (requestSequence === parseRequestSequence) setFeedbackError(feedback, error instanceof Error ? error.message : "解析任务状态读取失败");
  }
}

function latestJobMatchesScope(job: ParseJob, scope: LogMetricScope): boolean {
  const expected = analysisScopeUtcRange(scope);
  return job.package_name === scope.package_name
    && Date.parse(job.range_start_utc ?? "") === Date.parse(expected.range_start_utc)
    && Date.parse(job.range_end_utc ?? "") === Date.parse(expected.range_end_utc);
}

function clearParsePoll() { if (parsePollTimer !== null) { clearTimeout(parsePollTimer); parsePollTimer = null; } }

function scheduleParsePoll(scope: LogMetricScope, requestSequence: number) {
  clearParsePoll();
  if (requestSequence !== parseRequestSequence || !parseJob.value || !["pending", "running"].includes(parseJob.value.status)) return;
  parsePollTimer = setTimeout(() => { parsePollTimer = null; void pollParseJob(scope, requestSequence); }, 1000);
}

async function pollParseJob(scope: LogMetricScope, requestSequence: number) {
  if (requestSequence !== parseRequestSequence || !parseJob.value) return;
  try {
    const response = await getParseJob(parseJob.value.id);
    if (requestSequence !== parseRequestSequence) return;
    const candidate = responseData<ParseJob>(response);
    if (!latestJobMatchesScope(candidate, scope)) { parseJob.value = null; return; }
    parseJob.value = candidate;
    if (parseJob.value.status === "success") {
      refreshMetrics();
    }
    scheduleParsePoll(scope, requestSequence);
  } catch (error) {
    if (requestSequence === parseRequestSequence) {
      setFeedbackError(feedback, error instanceof Error ? error.message : "解析任务状态读取失败");
      scheduleParsePoll(scope, requestSequence);
    }
  }
}

function applyAnalysisScope(value: LogAnalysisFilterValues): LogMetricScope | null {
  const scope = analysisScopeFromFilters(value);
  const error = validateAnalysisScope(scope);
  if (error) { setFeedbackError(feedback, error); return null; }
  appliedFilters.value = { ...value };
  metricScope.value = scope;
  return scope;
}

function queryAnalysis(value: LogAnalysisFilterValues) {
  const scope = applyAnalysisScope(value);
  if (!scope) return;
  void loadLatestParseJob(scope);
  void loadPackageProfile(scope.package_name);
}

function refreshAnalysis(value: LogAnalysisFilterValues) {
  const scope = applyAnalysisScope(value);
  if (!scope) return;
  void loadLatestParseJob(scope);
  void loadPackageProfile(scope.package_name);
}

function resetAnalysis(value: LogAnalysisFilterValues) {
  clearParsePoll();
  ++parseRequestSequence;
  ++profileRequestSequence;
  parseJob.value = null;
  packageProfile.value = null;
  appliedFilters.value = { ...value };
  metricScope.value = { package_name: "", date_from: value.date_from, hour_from: value.hour_from, date_to: value.date_to, hour_to: value.hour_to };
}

async function requestParse(snapshot: LogMetricScope) {
  if (parseStarting.value || parseCancelling.value) return;
  const scope = applyAnalysisScope({ ...draftFilters.value, ...snapshot });
  if (!scope) return;
  clearParsePoll();
  parseJob.value = null;
  const requestSequence = ++parseRequestSequence;
  void loadPackageProfile(scope.package_name);
  parseStarting.value = true;
  try {
    const response = await postParseJob(scope);
    if (requestSequence !== parseRequestSequence) return;
    const candidate = responseData<ParseJob>(response);
    parseJob.value = latestJobMatchesScope(candidate, scope) ? candidate : null;
    scheduleParsePoll(scope, requestSequence);
  } catch (error) {
    if (requestSequence === parseRequestSequence) setFeedbackError(feedback, error instanceof Error ? error.message : "解析任务创建失败");
  } finally { parseStarting.value = false; }
}

async function requestCancel(jobId: number) {
  if (parseCancelling.value || !parseJob.value || parseJob.value.id !== jobId) return;
  const requestGeneration = parseRequestSequence;
  const cancelScope = { ...metricScope.value };
  const previousJob = parseJob.value;
  clearParsePoll();
  parseCancelling.value = true;
  try {
    const response = await cancelParseJob(jobId);
    if (requestGeneration !== parseRequestSequence) return;
    const candidate = responseData<ParseJob>(response);
    if (!latestJobMatchesScope(candidate, cancelScope)) return;
    parseJob.value = candidate;
    scheduleParsePoll(cancelScope, requestGeneration);
  } catch (error) {
    if (requestGeneration === parseRequestSequence) {
      parseJob.value = previousJob;
      setFeedbackError(feedback, error instanceof Error ? error.message : "解析任务取消失败");
      scheduleParsePoll(cancelScope, requestGeneration);
    }
  } finally { parseCancelling.value = false; }
}
function refreshMetrics() { metricScope.value = { ...metricScope.value }; }
async function openFailureDrawer(selection: { target_kind: "web_element" | "ad_area"; config_id?: number }) {
  const requestSequence = ++failureRequestSequence;
  const scope = { ...metricScope.value };
  failureDrawerOpen.value = true; failureLoading.value = true; failureError.value = ""; failureItems.value = [];
  try {
    const response = await getMetricFailures({ ...scope, ...(parseJob.value?.snapshot_end_utc ? { snapshot_end_utc: parseJob.value.snapshot_end_utc } : {}), ...selection });
    if (requestSequence !== failureRequestSequence) return;
    let value: unknown = response;
    if (value && typeof value === "object" && "data" in value) value = (value as { data: unknown }).data;
    if (value && typeof value === "object" && "code" in value && "data" in value) value = (value as { data: unknown }).data;
    failureItems.value = value as FailureBreakdownItem[];
  } catch (error) {
    if (requestSequence === failureRequestSequence) { failureItems.value = []; failureError.value = error instanceof Error ? error.message : "失败明细读取失败"; }
  }
  finally { if (requestSequence === failureRequestSequence) failureLoading.value = false; }
}
function closeFailureDrawer() { ++failureRequestSequence; failureDrawerOpen.value = false; failureLoading.value = false; }
watch(metricScope, () => {
  ++failureRequestSequence;
  failureDrawerOpen.value = false;
  failureLoading.value = false;
  failureItems.value = [];
  failureError.value = "";
}, { deep: true });
function updatePackageProfile(payload: { field: "alias" | "company" | "account"; value: string; profile: Partial<PackageProfile> }) {
  if (payload.profile.package_name && payload.profile.package_name !== metricScope.value.package_name) return;
  packageProfile.value = { ...(packageProfile.value ?? { package_name: metricScope.value.package_name, alias: "", company: "", account: "" }), ...payload.profile, [payload.field]: payload.value };
}
function showProfileError(message: string) { setFeedbackError(feedback, message); }

async function saveColumns(columns: string[]) {
  columnSaving.value = true; columnSaveError.value = "";
  try { const response = await putLogAnalysisColumns({ columns }); const data = responseData<LogAnalysisColumns>(response); visibleColumns.value = [...(data.columns ?? columns)]; columnSettingsOpen.value = false; }
  catch (error) { columnSaveError.value = error instanceof Error ? error.message : "列配置保存失败"; setFeedbackError(feedback, columnSaveError.value); }
  finally { columnSaving.value = false; }
}

type RawFilters = { package_name: string; sdk_version: string; device_id: string; log_level: string; date_from: string; hour_from: string; date_to: string; hour_to: string };
const emptyRawFilters = (): RawFilters => ({ package_name: "", sdk_version: "", device_id: "", log_level: "", date_from: "", hour_from: "", date_to: "", hour_to: "" });
const rawFilters = reactive<RawFilters>(emptyRawFilters());
const appliedRawFilters = ref<RawFilters>(emptyRawFilters());
const hourOptions = Array.from({ length: 24 }, (_, value) => ({ value: String(value), label: `${String(value).padStart(2, "0")}:00–${String(value).padStart(2, "0")}:59` }));
const filterOptions = reactive<EventFilterOptions>({ package_names: [], sdk_versions: [] });
const filterOptionsError = ref("");
const filterOptionsLoading = ref(false);
let filterOptionsRequestSequence = 0;
const rawResult = reactive({ total: 0, items: [] as EventItem[] });
const rawPage = ref(1); const rawRequestedPage = ref(1); const rawPageSize = 20; const selected = ref<EventItem | null>(null); let rawRequestSequence = 0;
function display(value: unknown): string { return value == null || value === "" ? "-" : String(value); }
function levelClass(value: unknown): string { return typeof value === "string" ? `level-${value}` : "level-unknown"; }
function rawQueryParams(targetPage: number): EventQuery {
  const filters = appliedRawFilters.value;
  return { page: targetPage, page_size: rawPageSize, event_type: "log", package_name: filters.package_name || undefined, sdk_version: filters.sdk_version || undefined, device_id: filters.device_id || undefined, log_level: (filters.log_level || undefined) as LogLevel | undefined, date_from: filters.date_from || undefined, hour_from: filters.hour_from === "" ? undefined : Number(filters.hour_from), date_to: filters.date_to || undefined, hour_to: filters.hour_to === "" ? undefined : Number(filters.hour_to) };
}
function rawFilterValidationError(filters: RawFilters): string | null {
  const hasHourFrom = filters.hour_from !== "";
  const hasHourTo = filters.hour_to !== "";
  if (hasHourFrom !== hasHourTo) return "开始小时和结束小时必须同时选择。";
  if (hasHourFrom && (!filters.date_from || !filters.date_to)) return "选择小时后必须同时选择开始日期和结束日期。";
  if (filters.date_from && filters.date_to && filters.date_from > filters.date_to) return "开始日期不能晚于结束日期。";
  if (hasHourFrom && filters.date_from === filters.date_to && Number(filters.hour_from) > Number(filters.hour_to)) return "结束小时必须不早于开始小时。";
  return null;
}
async function queryRaw(): Promise<void> {
  const error = rawFilterValidationError(rawFilters);
  if (error) { setFeedbackError(feedback, error); return; }
  appliedRawFilters.value = { ...rawFilters };
  await loadLogs({ resetPage: true });
}
async function resetRaw(): Promise<void> {
  Object.assign(rawFilters, emptyRawFilters());
  appliedRawFilters.value = emptyRawFilters();
  filterOptions.sdk_versions = [];
  await loadLogs({ resetPage: true });
}
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
onBeforeUnmount(() => { ++failureRequestSequence; ++parseRequestSequence; ++profileRequestSequence; clearParsePoll(); });
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
.table { width: 100%; margin-top: 14px; border-collapse: collapse; }.table th, .table td { padding: 12px 10px; border-bottom: 1px solid rgba(255, 255, 255, .08); text-align: left; white-space: nowrap; }
.clickable-row { cursor: pointer; }.clickable-row.selected { background: rgba(214, 140, 69, .1); }.message-cell { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.level-tag { display: inline-block; padding: 4px 8px; border-radius: 999px; background: rgba(255, 255, 255, .08); }.level-debug { color: #c6cbd3; }.level-info { color: #8cc8ff; }.level-warn { color: #ffd27a; }.level-error { color: #ff9f96; }
.empty-state { color: var(--text-muted); text-align: center; }.pager { justify-content: space-between; margin-top: 16px; }.feedback { margin: 0; padding: 12px 14px; border-radius: 14px; background: rgba(255, 255, 255, .06); }.feedback.error { color: #ffb0a8; background: rgba(209, 89, 89, .18); }.feedback.success { color: #a8e5bd; background: rgba(73, 150, 99, .18); }
.modal-backdrop { position: fixed; inset: 0; z-index: 10; display: grid; place-items: center; padding: 20px; background: rgba(0, 0, 0, .55); }.modal-panel { width: min(760px, 100%); max-height: calc(100dvh - 40px); min-width: 0; overflow: auto; }
@media (max-width: 1200px) { .viewer-grid { grid-template-columns: 1fr; } }
</style>
