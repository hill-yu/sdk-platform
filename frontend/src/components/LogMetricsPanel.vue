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
        <div class="section-heading"><h4>配置分布</h4><span class="count">{{ configs.length }} 项</span></div>
        <div class="table-scroll metric-table-scroll">
          <table class="table"><thead><tr><th>配置</th><th>声明数</th><th>占比</th></tr></thead>
            <tbody>
              <tr v-for="item in configs" :key="String(item.config_id)"><td :data-testid="item.config_id === 'unknown' ? 'unknown-config' : undefined">{{ item.config_id }}</td><td>{{ item.declaration_count }}</td><td>{{ formatRate(item.share) }}</td></tr>
              <tr v-if="!configs.length"><td colspan="3" class="empty-state">暂无配置分布。</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="metric-section">
        <div class="section-heading"><h4>目标维度</h4><div class="tabs"><button data-testid="target-tab-web-element" :class="{ active: targetKind === 'web_element' }" type="button" @click="selectTarget('web_element')">网页元素</button><button data-testid="target-tab-ad-area" :class="{ active: targetKind === 'ad_area' }" type="button" @click="selectTarget('ad_area')">广告区域</button></div></div>
        <div class="table-scroll metric-table-scroll">
          <table class="table"><thead><tr><th>计划</th><th>实际</th><th>成功</th><th>失败</th><th>实际率</th><th>成功率</th><th>失败率</th><th>操作</th></tr></thead>
            <tbody><tr v-if="!targets.length"><td colspan="8" class="empty-state">暂无目标维度结果。</td></tr><tr v-for="item in targets" v-else :key="`${targetKind}-${item.planned_count}-${item.actual_count}`"><td>{{ item.planned_count }}</td><td>{{ item.actual_count }}</td><td>{{ item.success_count }}</td><td>{{ item.failure_count }}</td><td>{{ formatRate(item.actual_rate) }}</td><td>{{ formatRate(item.success_rate) }}</td><td>{{ formatRate(item.failure_rate) }}</td><td><button data-testid="metric-failure-button" class="ghost" type="button" @click="$emit('failure-select', { target_kind: targetKind })">失败明细</button></td></tr></tbody>
          </table>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from "vue";

import { getMetricConfigs, getMetricOverview, getMetricTargets } from "@/api/logMetrics";
import type { ConfigMetricItem, LogMetricScope, MetricOverview, TargetMetric } from "@/api/logMetrics";

const props = defineProps<{ scope: LogMetricScope }>();
defineEmits<{ "failure-select": [value: { target_kind: string }] }>();

const overview = ref<MetricOverview | null>(null);
const configs = ref<ConfigMetricItem[]>([]);
const targets = ref<Array<TargetMetric & { target_kind: string }>>([]);
const targetKind = ref("web_element");
const loading = ref(false);
const error = ref("");
const disabled = ref(false);

function unwrap<T>(response: unknown): T {
  let value = response && typeof response === "object" && "data" in response ? (response as { data?: unknown }).data : response;
  if (value && typeof value === "object" && "code" in value && "data" in value) value = (value as { data: unknown }).data;
  return value as T;
}

function validScope(scope: LogMetricScope) {
  return Boolean(scope.package_name && scope.date_from && scope.date_to);
}

async function load() {
  if (!validScope(props.scope)) { disabled.value = true; overview.value = null; return; }
  disabled.value = false; loading.value = true; error.value = "";
  try {
    const [overviewResponse, configsResponse] = await Promise.all([getMetricOverview(props.scope), getMetricConfigs(props.scope)]);
    overview.value = unwrap<MetricOverview>(overviewResponse);
    configs.value = unwrap<{ total: number; items: ConfigMetricItem[] }>(configsResponse).items;
    await selectTarget(targetKind.value, false);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "指标读取失败";
  } finally { loading.value = false; }
}

async function selectTarget(kind: string, reloadOverview = true) {
  targetKind.value = kind;
  if (!validScope(props.scope)) return;
  try {
    const response = await getMetricTargets({ ...props.scope, target_kind: kind });
    targets.value = unwrap<{ items: Array<TargetMetric & { target_kind: string }> }>(response).items;
  } catch (cause) {
    if (reloadOverview) error.value = cause instanceof Error ? cause.message : "目标指标读取失败";
  }
}

function formatRate(value: number | null) { return value === null ? "-" : `${Math.round(value * 100)}%`; }

watch(() => props.scope, () => { void load(); }, { deep: true });
onMounted(() => { void load(); });
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
.tabs { display: flex; gap: 6px; }
.tabs button, .ghost { border: 1px solid var(--border-soft); border-radius: 8px; background: transparent; color: var(--text-primary); padding: 6px 10px; cursor: pointer; }
.tabs button.active { background: rgba(182, 98, 43, .22); }
.feedback.error { color: var(--danger, #d9785d); }
.empty-state { color: var(--text-secondary); }
</style>
