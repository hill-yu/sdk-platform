<template>
  <div class="stack dashboard-page">
    <p v-if="errorMessage" data-testid="dashboard-error" class="feedback error">{{ errorMessage }}</p>
    <p v-if="loading" data-testid="dashboard-loading" class="feedback">正在加载数据...</p>
    <div class="dashboard-heading">
      <h2>数据大盘</h2>
      <span>示例数据 · 非生产环境</span>
    </div>
    <section class="stats-grid light-stats">
      <StatCard title="今日 PV" :value="summary.today_pv" :trend="trend(summary.today_pv, summary.yesterday_pv)" light />
      <StatCard title="今日 UV" :value="summary.today_uv" :trend="trend(summary.today_uv, summary.yesterday_uv)" light />
      <StatCard
        title="今日事件数"
        :value="summary.today_events"
        :trend="trend(summary.today_events, summary.yesterday_events)" light
      />
      <StatCard
        title="活跃设备"
        :value="summary.active_devices"
        :trend="trend(summary.active_devices, summary.yesterday_active_devices)" light
      />
    </section>

    <section class="panel light-panel">
      <div class="panel-header panel-toolbar">
        <span class="sr-only">事件趋势</span>
        <div class="controls">
          <select v-model="trendRange" @change="loadTrend">
            <option value="24h">24 小时</option>
            <option value="7d">7 天</option>
            <option value="30d">30 天</option>
          </select>
          <select v-model="trendType" @change="loadTrend">
            <option value="">全部事件</option>
            <option value="click">click</option>
            <option value="log">log</option>
          </select>
        </div>
      </div>
      <p v-if="!loading && trendLabels.length === 0" class="empty-state">当前没有可展示的趋势数据。</p>
      <TrendChart v-else :title="'事件趋势'" :labels="trendLabels" :counts="trendCounts" :uv="trendUvs" light />
    </section>

    <div class="dual-grid">
      <section class="panel light-panel">
        <div class="panel-header">
          <span class="sr-only">事件分布</span>
          <select v-model="breakdownDimension" @change="loadBreakdown">
            <option value="event_type">事件类型</option>
            <option value="page">页面</option>
            <option value="element">元素</option>
          </select>
        </div>
        <TrendChart v-if="breakdownLabels.length" :title="'事件分布'" :labels="breakdownLabels" :counts="breakdownCounts" pie light />
        <p v-if="breakdownLabels.length === 0" class="empty-state">当前没有可展示的分布数据。</p>
      </section>

      <section class="panel light-panel">
        <div class="panel-header">
          <h3>事件明细</h3>
          <button class="ghost" @click="loadEvents">刷新</button>
        </div>
        <div class="filters">
          <select v-model="eventTypeFilter">
            <option value="">全部事件</option>
            <option value="click">click</option>
            <option value="log">log</option>
          </select>
          <input v-model="packageNameFilter" type="text" placeholder="package_name" />
          <input v-model="dateFromFilter" type="date" />
          <input v-model="dateToFilter" type="date" />
          <button class="ghost" @click="loadEvents">筛选</button>
        </div>
        <div class="table-scroll">
          <table class="table">
            <thead>
              <tr>
                <th>时间</th>
                <th>事件类型</th>
                <th>设备 ID</th>
                <th>页面</th>
                <th>元素</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="events.items.length === 0">
                <td colspan="5" class="empty-state">当前筛选条件下没有事件数据。</td>
              </tr>
              <template v-for="item in events.items" :key="item.id">
              <tr class="clickable-row" @click="toggleExpanded(item.id)">
                <td>{{ formatBusinessTime(item.server_ts) }}</td>
                <td>{{ item.event_type }}</td>
                <td>{{ item.device_id || "-" }}</td>
                <td>{{ item.payload?.page || "-" }}</td>
                <td>{{ item.payload?.element || "-" }}</td>
              </tr>
              <tr v-if="expandedId === item.id" class="expanded-row">
                <td colspan="5">
                  <pre>{{ JSON.stringify(item.payload, null, 2) }}</pre>
                </td>
              </tr>
              </template>
            </tbody>
          </table>
        </div>
        <div class="pager">
          <button class="ghost" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
          <span>第 {{ page }} / {{ totalPages }} 页</span>
          <button class="ghost" :disabled="page >= totalPages" @click="changePage(page + 1)">下一页</button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";

import { getBreakdown, getEvents, getSummary, getTrend } from "@/api/dashboard";
import StatCard from "@/components/StatCard.vue";
import TrendChart from "@/components/TrendChart.vue";
import { formatBusinessTime } from "@/utils/dateTime";

const summary = reactive({
  today_pv: 0,
  yesterday_pv: 0,
  today_uv: 0,
  yesterday_uv: 0,
  today_events: 0,
  yesterday_events: 0,
  active_devices: 0,
  yesterday_active_devices: 0,
  error_count: 0,
});

const trendRange = ref("24h");
const trendType = ref("");
const breakdownDimension = ref("event_type");
const trendLabels = ref<string[]>([]);
const trendCounts = ref<number[]>([]);
const trendUvs = ref<number[]>([]);
const breakdownLabels = ref<string[]>([]);
const breakdownCounts = ref<number[]>([]);
const events = reactive<{ total: number; items: Array<Record<string, any>> }>({ total: 0, items: [] });
const errorMessage = ref("");
const loading = ref(false);
const page = ref(1);
const pageSize = ref(8);
const expandedId = ref<number | null>(null);
const eventTypeFilter = ref("");
const packageNameFilter = ref("");
const dateFromFilter = ref("");
const dateToFilter = ref("");
const totalPages = computed(() => Math.max(1, Math.ceil(events.total / pageSize.value)));

function trend(current: number, previous: number): number {
  if (!previous) return current > 0 ? 100 : 0;
  return ((current - previous) / previous) * 100;
}

async function loadSummary() {
  const response = await getSummary();
  Object.assign(summary, response.data);
}

async function loadTrend() {
  const response = await getTrend({ range: trendRange.value, event_type: trendType.value || undefined });
  trendLabels.value = response.data.points.map((point: Record<string, any>) => point.time);
  trendCounts.value = response.data.points.map((point: Record<string, any>) => Number(point.count));
  trendUvs.value = response.data.points.map((point: Record<string, any>) => Number(point.uv));
}

async function loadBreakdown() {
  const response = await getBreakdown({ dimension: breakdownDimension.value });
  breakdownLabels.value = response.data.map((item: Record<string, any>) => item.name);
  breakdownCounts.value = response.data.map((item: Record<string, any>) => Number(item.count));
}

async function loadEvents() {
  const response = await getEvents({
    page: page.value,
    page_size: pageSize.value,
    event_type: eventTypeFilter.value || undefined,
    package_name: packageNameFilter.value || undefined,
    date_from: dateFromFilter.value || undefined,
    date_to: dateToFilter.value || undefined,
  });
  events.total = response.data.total;
  events.items = response.data.items;
  expandedId.value = null;
}

function toggleExpanded(id: number) {
  expandedId.value = expandedId.value === id ? null : id;
}

async function changePage(nextPage: number) {
  page.value = nextPage;
  await loadEvents();
}

onMounted(async () => {
  try {
    loading.value = true;
    errorMessage.value = "";
    await Promise.all([loadSummary(), loadTrend(), loadBreakdown(), loadEvents()]);
  } catch (error) {
    errorMessage.value = (error as Error).message;
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.stack {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
  min-height: 0;
}

.dashboard-page { gap: 16px; }
.dashboard-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; }
.dashboard-heading h2 { margin: 0; color: var(--text-primary); font-size: 26px; letter-spacing: -0.03em; }
.dashboard-heading span { color: var(--text-muted); font-size: 13px; }

.stats-grid,
.dual-grid {
  display: grid;
  gap: 18px;
}

.stats-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.light-stats { padding: 0; overflow: hidden; border: 1px solid var(--border-soft); border-radius: 6px; background: var(--panel-bg); }

.dual-grid {
  grid-template-columns: 1fr 3fr;
}

.stats-grid > *,
.dual-grid > *,
.panel,
.panel-header,
.controls,
.filters,
.pager {
  min-width: 0;
}

.stats-grid > *,
.dual-grid > * {
  min-height: 0;
}

.panel {
  padding: 22px;
  border-radius: 24px;
  background: var(--panel-bg);
  border: 1px solid var(--border-soft);
  box-shadow: var(--panel-shadow);
}

.light-panel { padding: 18px; border-radius: 6px; background: var(--panel-bg); border-color: var(--border-soft); box-shadow: var(--panel-shadow); }
.light-panel select, .light-panel input, .light-panel .ghost { border-radius: 6px; }
.dashboard-page h3 { color: var(--text-primary); }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }

.panel-header,
.controls,
.filters,
.pager {
  display: flex;
  align-items: center;
  gap: 12px;
}

.filters { flex-wrap: wrap; }

.panel-header,
.pager {
  justify-content: space-between;
}

.panel-toolbar .controls,
.light-panel > .panel-header > select { margin-left: auto; }

select,
.ghost,
input {
  background: var(--panel-bg);
  color: var(--text-primary);
  border: 1px solid var(--border-soft);
  border-radius: 12px;
  padding: 10px 12px;
}

.light-panel select, .light-panel input, .light-panel .ghost { color: var(--text-primary); background: var(--panel-bg); border-color: var(--border-soft); }
.light-panel .filters input { min-width: 0; flex: 1 1 130px; }
.light-panel .filters select, .light-panel .filters .ghost { flex: 0 1 auto; }
.light-panel select:focus-visible, .light-panel input:focus-visible, .light-panel button:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; }

.feedback {
  margin: 0;
  padding: 12px 14px;
  border-radius: 14px;
  background: var(--surface-raised);
}

.feedback.error {
  background: var(--error-bg);
  color: var(--error-text);
}

.table-scroll {
  min-width: 0;
  max-width: 100%;
  overflow-x: auto;
}

.table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 14px;
}

.table th,
.table td {
  text-align: left;
  padding: 12px 10px;
  border-bottom: 1px solid var(--border-soft);
}

.clickable-row {
  cursor: pointer;
}

.expanded-row pre {
  margin: 0;
  max-width: 100%;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-muted);
}

.empty-state {
  color: var(--text-muted);
  text-align: center;
}

.light-panel .empty-state { color: var(--text-muted); padding: 32px 12px; }
.light-panel .table th, .light-panel .table td { padding: 3px 10px; border-bottom-color: var(--border-soft); color: var(--text-primary); }
.light-panel .expanded-row pre { color: var(--text-secondary); background: var(--code-bg); }
.light-panel .pager { color: var(--text-muted); }
.dashboard-page :deep(.chart) { height: 220px; }
.dashboard-page .table { min-width: 680px; }

@media (prefers-reduced-motion: reduce) {
  .dashboard-page *, .dashboard-page *::before, .dashboard-page *::after { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
}

@media (max-width: 1120px) {
  .stats-grid,
  .dual-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .light-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .light-stats > * { border-bottom: 1px solid var(--border-soft); }
  .light-stats > *:nth-child(even) { border-right: 0; }
  .dual-grid { gap: 12px; }
  .panel-header, .controls { flex-wrap: wrap; }
  .dashboard-heading { align-items: flex-start; flex-direction: column; gap: 4px; }
  .card.light .value-row { align-items: flex-start; flex-direction: column; gap: 4px; }
  .card.light .trend-wrap { gap: 6px; }
  .panel-toolbar .controls { width: 100%; margin-left: 0; }
  .panel-toolbar .controls select { flex: 1 1 0; min-width: 0; }
  .light-panel { overflow: hidden; }
  .light-panel .chart { max-width: 100%; }
  .filters { align-items: stretch; }
  .filters > * { min-width: min(100%, 140px); }
}
</style>
