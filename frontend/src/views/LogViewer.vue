<template>
  <div class="stack">
    <p v-if="feedback.error" data-testid="error-feedback" class="feedback error">{{ feedback.error }}</p>
    <p v-if="feedback.success" data-testid="success-feedback" class="feedback success">{{ feedback.success }}</p>

    <section class="panel filters-panel">
      <div class="filters">
        <input v-model="filters.package_name" data-testid="package-filter" type="text" placeholder="package_name" />
        <select v-model="filters.log_level" data-testid="level-filter">
          <option value="">全部级别</option>
          <option value="debug">debug</option>
          <option value="info">info</option>
          <option value="warn">warn</option>
          <option value="error">error</option>
        </select>
        <input v-model="filters.device_id" data-testid="device-filter" type="text" placeholder="device_id" />
        <input v-model="filters.date_from" data-testid="date-from-filter" type="date" />
        <input v-model="filters.date_to" data-testid="date-to-filter" type="date" />
        <button data-testid="query-button" class="primary" type="button" @click="loadLogs({ resetPage: true })">
          查询
        </button>
        <button data-testid="refresh-button" class="ghost" type="button" @click="loadLogs()">刷新</button>
      </div>
    </section>

    <div class="viewer-grid">
      <section class="panel list-panel">
        <div class="panel-header">
          <h3>日志列表</h3>
          <span class="count">共 {{ result.total }} 条</span>
        </div>
        <div data-testid="log-list" class="table-scroll">
          <table class="table">
            <thead>
              <tr>
                <th>时间</th>
                <th>级别</th>
                <th>包名</th>
                <th>设备 ID</th>
                <th>SDK 版本</th>
                <th>tag</th>
                <th>message</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="result.items.length === 0">
                <td data-testid="empty-state" colspan="7" class="empty-state">当前筛选条件下没有日志。</td>
              </tr>
              <tr
                v-for="item in result.items"
                :key="item.id"
                data-testid="log-row"
                class="clickable-row"
                :class="{ selected: selected?.id === item.id }"
                @click="selected = item"
              >
                <td>{{ display(item.server_ts) }}</td>
                <td>
                  <span data-testid="level-tag" class="level-tag" :class="levelClass(item.payload.level)">
                    {{ display(item.payload.level) }}
                  </span>
                </td>
                <td>{{ display(item.package_name) }}</td>
                <td>{{ display(item.device_id) }}</td>
                <td>{{ display(item.sdk_version) }}</td>
                <td data-testid="log-tag">{{ display(item.payload.tag) }}</td>
                <td data-testid="log-message" class="message-cell" :title="display(item.payload.message)">
                  {{ display(item.payload.message) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="pager">
          <button
            data-testid="previous-page"
            class="ghost"
            type="button"
            :disabled="page <= 1"
            @click="changePage(requestedPage - 1)"
          >
            上一页
          </button>
          <span>第 {{ page }} / {{ totalPages }} 页</span>
          <button
            data-testid="next-page"
            class="ghost"
            type="button"
            :disabled="page >= totalPages"
            @click="changePage(requestedPage + 1)"
          >
            下一页
          </button>
        </div>
      </section>

      <section class="panel detail-panel">
        <div class="panel-header"><h3>日志详情</h3></div>
        <LogDetail :item="selected" @copy-success="showCopySuccess" @copy-error="showCopyError" />
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";

import { getEvents } from "@/api/dashboard";
import type { EventItem, EventQuery, LogLevel } from "@/api/dashboard";
import LogDetail from "@/components/LogDetail.vue";
import { beginFeedback, setFeedbackError, setFeedbackSuccess } from "@/utils/feedback";

const filters = reactive({ package_name: "", device_id: "", log_level: "", date_from: "", date_to: "" });
const result = reactive({ total: 0, items: [] as EventItem[] });
const page = ref(1);
const requestedPage = ref(1);
const pageSize = 20;
const selected = ref<EventItem | null>(null);
const feedback = reactive({ error: "", success: "" });
const totalPages = computed(() => Math.max(1, Math.ceil(result.total / pageSize)));
let latestRequest = 0;

function display(value: unknown): string {
  return value == null || value === "" ? "-" : String(value);
}

function levelClass(value: unknown): string {
  return typeof value === "string" ? `level-${value}` : "level-unknown";
}

function queryParams(targetPage: number): EventQuery {
  return {
    page: targetPage,
    page_size: pageSize,
    event_type: "log",
    package_name: filters.package_name || undefined,
    device_id: filters.device_id || undefined,
    log_level: (filters.log_level || undefined) as LogLevel | undefined,
    date_from: filters.date_from || undefined,
    date_to: filters.date_to || undefined,
  };
}

async function loadLogs(options: { resetPage?: boolean; targetPage?: number } = {}): Promise<void> {
  const targetPage = options.resetPage ? 1 : (options.targetPage ?? page.value);
  requestedPage.value = targetPage;
  const requestId = ++latestRequest;
  beginFeedback(feedback);
  try {
    const response = await getEvents(queryParams(targetPage));
    if (requestId !== latestRequest) return;
    result.total = response.data.total;
    result.items = response.data.items;
    page.value = targetPage;
    requestedPage.value = targetPage;
    if (selected.value) {
      selected.value = result.items.find((item) => item.id === selected.value?.id) ?? null;
    }
  } catch (error) {
    if (requestId !== latestRequest) return;
    requestedPage.value = page.value;
    setFeedbackError(feedback, error instanceof Error ? error.message : "日志查询失败");
  }
}

async function changePage(nextPage: number): Promise<void> {
  await loadLogs({ targetPage: nextPage });
}

function showCopySuccess(): void {
  setFeedbackSuccess(feedback, "extra 复制成功");
}

function showCopyError(message: string): void {
  setFeedbackError(feedback, message);
}

onMounted(() => loadLogs());
</script>

<style scoped>
.stack { display: flex; flex-direction: column; gap: 20px; }
.panel { padding: 22px; border: 1px solid var(--border-soft); border-radius: 24px; background: var(--panel-bg); box-shadow: var(--panel-shadow); }
.filters, .panel-header, .pager { display: flex; align-items: center; gap: 12px; }
.filters { flex-wrap: wrap; }
.viewer-grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr); gap: 18px; align-items: start; }
.panel-header, .pager { justify-content: space-between; }
.panel-header h3 { margin: 0; }
.count { color: var(--text-muted); }
select, input, button { padding: 10px 12px; border: 1px solid var(--border-soft); border-radius: 12px; color: var(--text-primary); background: rgba(255, 255, 255, 0.05); }
.primary { border-color: rgba(214, 140, 69, 0.5); background: rgba(214, 140, 69, 0.24); }
button:disabled { cursor: not-allowed; opacity: 0.45; }
.feedback { margin: 0; padding: 12px 14px; border-radius: 14px; background: rgba(255, 255, 255, 0.06); }
.feedback.error { color: #ffb0a8; background: rgba(209, 89, 89, 0.18); }
.feedback.success { color: #a8e5bd; background: rgba(73, 150, 99, 0.18); }
.table-scroll { overflow-x: auto; }
.table { width: 100%; margin-top: 14px; border-collapse: collapse; }
.table th, .table td { padding: 12px 10px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); text-align: left; }
.clickable-row { cursor: pointer; }
.clickable-row.selected { background: rgba(214, 140, 69, 0.1); }
.message-cell { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.level-tag { display: inline-block; padding: 4px 8px; border-radius: 999px; background: rgba(255, 255, 255, 0.08); }
.level-debug { color: #c6cbd3; }.level-info { color: #8cc8ff; }.level-warn { color: #ffd27a; }.level-error { color: #ff9f96; }
.empty-state { color: var(--text-muted); text-align: center; }
.pager { margin-top: 16px; }
@media (max-width: 1200px) { .viewer-grid { grid-template-columns: 1fr; } }
</style>
