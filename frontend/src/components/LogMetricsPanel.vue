<template>
  <section class="metrics-panel" data-testid="metrics-panel">
    <div class="panel-header">
      <div><h3>结构化指标</h3><p class="scope-note">{{ scope.package_name }} · {{ scope.date_from }} {{ scope.hour_from }}:00 至 {{ scope.date_to }} {{ scope.hour_to }}:00（北京时间）</p></div>
      <span v-if="loading" class="count">加载中…</span>
    </div>

    <p v-if="disabled" data-testid="metrics-disabled" class="empty-state">请输入包名并查询已有结果，或先开始解析任务。</p>
    <p v-else-if="error" data-testid="metrics-error" class="feedback error">{{ error }}</p>
    <p v-else-if="!loading && !overview" data-testid="metrics-empty" class="empty-state">当前条件下暂无指标结果。</p>
    <template v-else-if="overview">
      <div class="metric-cards">
        <article><span>声明点击数</span><strong data-testid="declaration-count">{{ overview.declaration_count }}</strong></article>
        <article><span>计划点击数</span><strong data-testid="planned-click-count">{{ overview.planned_click_count }}</strong></article>
        <article><span>实际点击数</span><strong data-testid="actual-click-count">{{ overview.actual_click_count }}</strong></article>
        <article><span>响应成功数</span><strong data-testid="response-success-count">{{ overview.response_success_count }}</strong></article>
        <article><span>插屏关闭率</span><strong data-testid="interstitial-close-rate">{{ formatRate(overview.interstitial_close_rate) }}</strong></article>
        <article><span>非关闭点击率</span><strong>{{ formatRate(overview.interstitial_non_close_click_rate) }}</strong></article>
      </div>
      <p v-if="overview.plan_mismatch_count > 0" data-testid="plan-mismatch-alert" class="mismatch-alert">计划与实际点击数存在 {{ overview.plan_mismatch_count }} 条不一致，请查看失败明细。</p>

      <div class="metric-section">
        <div class="section-heading"><h4>配置分布</h4><div class="config-tabs"><button data-testid="config-select-all" :class="{ active: selectedConfigId === null }" type="button" @click="selectConfig(null)">全部配置</button></div></div>
        <div class="table-scroll metric-table-scroll">
          <table class="table"><thead><tr><th>配置</th><th>声明数</th><th>占比</th></tr></thead>
            <tbody>
              <tr v-for="item in configs" :key="String(item.config_id)">
                <td>
                  <button v-if="item.config_id !== 'unknown'" :data-testid="`config-select-${item.config_id}`" :class="{ active: selectedConfigId === item.config_id }" class="config-button" type="button" @click="selectConfig(item.config_id)">{{ item.config_id }}</button>
                  <button v-else data-testid="config-select-unknown" class="config-button" type="button" disabled title="unknown 配置无法精确下钻，请选择全部配置"><span data-testid="unknown-config">unknown</span></button>
                </td>
                <td>{{ item.declaration_count }}</td><td>{{ formatRate(item.share) }}</td>
              </tr>
              <tr v-if="!configs.length"><td colspan="3" class="empty-state">暂无配置分布。</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="metric-section">
        <div class="section-heading"><h4>目标维度</h4><div class="tabs"><button data-testid="target-tab-web-element" :class="{ active: targetKind === 'web_element' }" type="button" @click="selectTarget('web_element')">网页元素</button><button data-testid="target-tab-ad-area" :class="{ active: targetKind === 'ad_area' }" type="button" @click="selectTarget('ad_area')">广告区域</button></div></div>
        <div class="table-scroll metric-table-scroll">
          <table class="table"><thead><tr><th>计划</th><th>实际</th><th>成功</th><th>失败</th><th>实际率</th><th>成功率</th><th>失败率</th></tr></thead>
            <tbody>
              <tr v-if="!visibleTargets.length"><td colspan="7" class="empty-state">暂无目标维度结果。</td></tr>
              <tr v-for="item in visibleTargets" v-else :key="targetKind" data-testid="target-row">
                <td>{{ item.planned_count }}</td><td>{{ item.actual_count }}</td><td>{{ item.success_count }}</td>
                <td><button data-testid="metric-failure-button" class="failure-count" type="button" @click="emitFailureSelection">{{ item.failure_count }}</button></td>
                <td>{{ formatRate(item.actual_rate) }}</td><td>{{ formatRate(item.success_rate) }}</td><td>{{ formatRate(item.failure_rate) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { getMetricConfigs, getMetricOverview, getMetricTargets } from "@/api/logMetrics";
import type { ConfigMetricItem, LogMetricScope, MetricOverview, TargetMetric } from "@/api/logMetrics";

type MetricViewKind = "web_element" | "ad_area";
type VisibleTarget = Omit<TargetMetric, "target_kind">;

const props = defineProps<{ scope: LogMetricScope }>();
const emit = defineEmits<{ "failure-select": [value: { target_kind: MetricViewKind; config_id?: number }] }>();

const overview = ref<MetricOverview | null>(null);
const configs = ref<ConfigMetricItem[]>([]);
const rawTargets = ref<TargetMetric[]>([]);
const targetKind = ref<MetricViewKind>("web_element");
const selectedConfigId = ref<number | null>(null);
const loading = ref(false);
const error = ref("");
const disabled = ref(false);
let disposed = false;
let scopeRequestId = 0;
let targetRequestId = 0;

const visibleTargets = computed<VisibleTarget[]>(() => {
  const allowed = targetKind.value === "web_element" ? rawTargets.value.filter((item) => item.target_kind === "web_element") : rawTargets.value.filter((item) => item.target_kind === "banner" || item.target_kind === "anchored");
  if (!allowed.length) return [];
  const totals = allowed.reduce((result, item) => ({
    planned_count: result.planned_count + item.planned_count,
    actual_count: result.actual_count + item.actual_count,
    success_count: result.success_count + item.success_count,
    failure_count: result.failure_count + item.failure_count,
  }), { planned_count: 0, actual_count: 0, success_count: 0, failure_count: 0 });
  return [{ ...totals, actual_rate: ratio(totals.actual_count, totals.planned_count), success_rate: ratio(totals.success_count, totals.planned_count), failure_rate: ratio(totals.failure_count, totals.planned_count) }];
});

function ratio(numerator: number, denominator: number) { return denominator ? numerator / denominator : null; }

function unwrap<T>(response: unknown): T {
  let value = response && typeof response === "object" && "data" in response ? (response as { data?: unknown }).data : response;
  if (value && typeof value === "object" && "code" in value && "data" in value) value = (value as { data: unknown }).data;
  return value as T;
}

function validScope(scope: LogMetricScope) { return Boolean(scope.package_name && scope.date_from && scope.date_to); }

async function loadTargets(scope: LogMetricScope, requestId: number, kind: MetricViewKind) {
  const targetRequest = ++targetRequestId;
  const response = await getMetricTargets(scope);
  if (disposed || requestId !== scopeRequestId || targetRequest !== targetRequestId || targetKind.value !== kind) return;
  rawTargets.value = unwrap<{ items: TargetMetric[] }>(response).items;
}

async function load() {
  const requestId = ++scopeRequestId;
  ++targetRequestId;
  const scope = { ...props.scope };
  selectedConfigId.value = null;
  if (!validScope(scope)) { disabled.value = true; overview.value = null; rawTargets.value = []; return; }
  disabled.value = false; loading.value = true; error.value = "";
  try {
    const [overviewResponse, configsResponse] = await Promise.all([getMetricOverview(scope), getMetricConfigs(scope)]);
    if (disposed || requestId !== scopeRequestId) return;
    overview.value = unwrap<MetricOverview>(overviewResponse);
    configs.value = unwrap<{ total: number; items: ConfigMetricItem[] }>(configsResponse).items;
    await loadTargets(scope, requestId, targetKind.value);
  } catch (cause) {
    if (!disposed && requestId === scopeRequestId) { error.value = cause instanceof Error ? cause.message : "指标读取失败"; rawTargets.value = []; }
  } finally {
    if (!disposed && requestId === scopeRequestId) loading.value = false;
  }
}

async function selectTarget(kind: MetricViewKind) {
  targetKind.value = kind;
  if (!validScope(props.scope)) return;
  const requestId = scopeRequestId;
  const scope = { ...props.scope };
  error.value = "";
  try {
    await loadTargets(scope, requestId, kind);
  } catch (cause) {
    if (!disposed && requestId === scopeRequestId && targetKind.value === kind) { error.value = cause instanceof Error ? cause.message : "目标指标读取失败"; rawTargets.value = []; }
  }
}

function selectConfig(configId: number | null) { selectedConfigId.value = configId; }
function emitFailureSelection() { emit("failure-select", selectedConfigId.value === null ? { target_kind: targetKind.value } : { target_kind: targetKind.value, config_id: selectedConfigId.value }); }
function formatRate(value: number | null) { return value === null ? "-" : `${Math.round(value * 100)}%`; }

watch(() => props.scope, () => { void load(); }, { deep: true });
onMounted(() => { void load(); });
onBeforeUnmount(() => { disposed = true; ++scopeRequestId; ++targetRequestId; });
</script>

<style scoped>
.metrics-panel { display: grid; gap: 16px; }
.panel-header, .section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.panel-header h3, .section-heading h4 { margin: 0; }
.scope-note { margin: 4px 0 0; color: var(--text-secondary); font-size: 12px; }
.metric-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
.metric-cards article { display: grid; gap: 8px; padding: 14px; border: 1px solid var(--border-soft); border-radius: 10px; background: rgba(8, 13, 13, .35); }
.metric-cards span { color: var(--text-secondary); font-size: 12px; }
.metric-cards strong { font-size: 22px; }
.metric-section { display: grid; gap: 10px; }
.metric-table-scroll { max-height: 250px; overflow: auto; }
.mismatch-alert { margin: 0; padding: 10px 12px; border: 1px solid rgba(217, 120, 93, .45); border-radius: 8px; color: var(--danger, #d9785d); }
.tabs, .config-tabs { display: flex; gap: 6px; }
.tabs button, .config-tabs button, .ghost, .config-button, .failure-count { border: 1px solid var(--border-soft); border-radius: 8px; background: transparent; color: var(--text-primary); padding: 6px 10px; cursor: pointer; }
.tabs button.active, .config-tabs button.active, .config-button.active { background: rgba(182, 98, 43, .22); }
.config-button:disabled { cursor: not-allowed; opacity: .6; }
.failure-count { min-width: 34px; color: var(--text-primary); }
.feedback.error { color: var(--danger, #d9785d); }
.empty-state { color: var(--text-secondary); }
</style>
