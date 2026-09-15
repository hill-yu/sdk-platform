<template>
  <section class="analysis-detail" aria-label="解析明细">
    <div class="detail-header">
      <div>
        <h3>解析明细</h3>
        <span class="count">共 {{ total }} 条</span>
      </div>
      <p v-if="error" data-testid="detail-error" class="error" role="alert">{{ error }}</p>
    </div>

    <div class="table-scroll">
      <table class="detail-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>状态</th>
            <th>包名</th>
            <th>设备 ID</th>
            <th>URL</th>
            <th>计划点击</th>
            <th>实际点击</th>
            <th>耗时</th>
            <th>最终原因</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!items.length">
            <td colspan="9" class="empty-state">{{ loading ? "加载中…" : "当前分组没有解析明细。" }}</td>
          </tr>
          <tr
            v-for="item in items"
            v-else
            :key="`${item.event_id}-${item.event_server_ts}-${item.record_index}`"
            data-testid="analysis-detail-row"
            class="clickable-row"
            :class="{ selected: selected === item }"
            @click="emit('select', item)"
          >
            <td>{{ formatBusinessTime(item.event_server_ts) }}</td>
            <td><span :class="['status-tag', `status-${item.status}`]">{{ item.status }}</span></td>
            <td>{{ display(item.package_name) }}</td>
            <td>{{ display(item.device_id) }}</td>
            <td>{{ display(item.url) }}</td>
            <td>{{ display(item.expected_click_count) }}</td>
            <td>{{ display(item.actual_click_count) }}</td>
            <td>{{ item.duration_ms == null ? "-" : `${item.duration_ms} ms` }}</td>
            <td>{{ display(item.final_reason) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="pager">
      <button data-testid="detail-previous-page" type="button" :disabled="page <= 1 || loading" @click="changePage(page - 1)">上一页</button>
      <span>第 {{ page }} / {{ totalPages }} 页</span>
      <button data-testid="detail-next-page" type="button" :disabled="page >= totalPages || loading" @click="changePage(page + 1)">下一页</button>
    </div>

    <section v-if="detail" class="detail-inspector" aria-label="解析详情内容">
      <h4>完整解析详情</h4>
      <dl class="detail-summary">
        <div><dt>事件键</dt><dd>{{ detail.event_id }} / {{ detail.record_index }}</dd></div>
        <div><dt>解析时间</dt><dd>{{ formatBusinessTime(detail.parsed_at) }}</dd></div>
        <div><dt>解码时间</dt><dd>{{ formatBusinessTime(detail.decoded_timestamp) }}</dd></div>
        <div><dt>解析错误</dt><dd>{{ display(detail.parse_error) }}</dd></div>
      </dl>
      <h5>结构化 JSON</h5>
      <pre data-testid="decoded-json">{{ serialize(detail.decoded_payload) }}</pre>
      <h5>原始 extra</h5>
      <pre data-testid="raw-extra">{{ display(detail.extra) }}</pre>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";

import type { LogDecodeItem } from "@/api/logAnalysis";
import { formatBusinessTime } from "@/utils/dateTime";

const props = withDefaults(
  defineProps<{
    items: LogDecodeItem[];
    total?: number;
    page?: number;
    pageSize?: number;
    loading?: boolean;
    error?: string | null;
    selected?: LogDecodeItem | null;
    detail?: LogDecodeItem | null;
  }>(),
  { total: 0, page: 1, pageSize: 20, loading: false, error: null, selected: null, detail: null },
);

const emit = defineEmits<{
  select: [item: LogDecodeItem];
  "page-change": [page: number];
}>();

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)));

function display(value: unknown): string {
  return value == null || value === "" ? "-" : String(value);
}

function serialize(value: unknown): string {
  if (value == null) return "-";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return display(value);
  }
}

function changePage(nextPage: number) {
  const bounded = Math.min(totalPages.value, Math.max(1, nextPage));
  if (bounded !== props.page) emit("page-change", bounded);
}
</script>

<style scoped>
.analysis-detail { display: grid; gap: 14px; }
.detail-header, .detail-header > div, .pager { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h3, h4, h5, p { margin: 0; }
.count { color: var(--text-muted); font-size: 12px; }
.error { color: #ffb0a8; font-size: 12px; }
.table-scroll { overflow-x: auto; }
.detail-table { width: max-content; min-width: 100%; border-collapse: collapse; }
.detail-table th, .detail-table td { padding: 10px; border-bottom: 1px solid rgba(255, 255, 255, .08); text-align: left; white-space: nowrap; }
.clickable-row { cursor: pointer; }
.clickable-row.selected { background: rgba(214, 140, 69, .12); }
.empty-state { width: 100%; color: var(--text-muted); text-align: center; }
.status-tag { border-radius: 999px; padding: 4px 8px; background: rgba(255, 255, 255, .08); }
.status-success { color: #a8e5bd; }.status-failed { color: #ffb0a8; }.status-unsupported { color: #ffd27a; }
button { border: 1px solid var(--border-soft); border-radius: 8px; background: rgba(8, 13, 13, .5); color: var(--text-primary); padding: 7px 11px; cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .5; }
.detail-inspector { display: grid; gap: 10px; border-top: 1px solid var(--border-soft); padding-top: 14px; }
.detail-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; margin: 0; }
.detail-summary div { padding: 8px; border-radius: 8px; background: rgba(255, 255, 255, .04); }
dt { color: var(--text-muted); font-size: 11px; } dd { margin: 3px 0 0; color: var(--text-primary); font-size: 12px; }
pre { max-height: 280px; overflow: auto; margin: 0; border-radius: 8px; background: rgba(0, 0, 0, .25); color: var(--text-secondary); padding: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
