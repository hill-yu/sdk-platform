<template>
  <section class="panel history-panel" data-testid="history-panel">
    <div class="panel-header"><h3>历史解析结果</h3><div class="history-actions"><button class="ghost" type="button" @click="toggleExpanded">{{ expanded ? "收起" : "展开" }}</button><button v-if="expanded" class="ghost" type="button" :disabled="loading" @click="load(1)">刷新</button></div></div>
    <template v-if="expanded">
      <p v-if="error" data-testid="history-error" class="feedback error">{{ error }}</p>
      <p v-else-if="loading" data-testid="history-loading" class="empty-state">加载中…</p>
      <p v-else-if="!jobs.length" data-testid="history-empty" class="empty-state">暂无可读取的历史解析结果。</p>
      <div v-else class="history-list">
      <button v-for="job in jobs" :key="job.id" type="button" data-testid="history-job" :disabled="job.historical_available === false" :class="{ active: selectedJobId === job.id }" @click="job.historical_available !== false && emit('select', job)">
        <span>#{{ job.id }} · {{ job.package_name }} · {{ job.status }}</span><small>{{ job.range_start }} 至 {{ job.range_end }}{{ job.error_summary ? ` · ${job.error_summary}` : "" }}</small>
      </button>
      </div>
      <div v-if="total > pageSize" class="history-pagination">
        <button data-testid="history-prev" class="ghost" type="button" :disabled="loading || page <= 1" @click="load(page - 1)">上一页</button>
        <span data-testid="history-page">第 {{ page }} / {{ pageCount }} 页</span>
        <button data-testid="history-next" class="ghost" type="button" :disabled="loading || page >= pageCount" @click="load(page + 1)">下一页</button>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { getHistoricalParseJobs } from "@/api/logMetrics";
import type { ParseJob } from "@/api/logMetrics";

const props = withDefaults(defineProps<{ packageName?: string; selectedJobId?: number | null }>(), { packageName: "", selectedJobId: null });
const emit = defineEmits<{ select: [job: ParseJob] }>();
const jobs = ref<ParseJob[]>([]);
const loading = ref(false);
const error = ref("");
const expanded = ref(false);
const page = ref(1);
const total = ref(0);
const pageSize = 10;
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
let requestId = 0;
function unwrap<T>(response: unknown): T {
  let value = response && typeof response === "object" && "data" in response ? (response as { data?: unknown }).data : response;
  if (value && typeof value === "object" && "code" in value && "data" in value) value = (value as { data: unknown }).data;
  return value as T;
}
async function load(nextPage = page.value) {
  const current = ++requestId;
  page.value = nextPage;
  loading.value = true; error.value = ""; jobs.value = [];
  try {
    const response = await getHistoricalParseJobs({ package_name: props.packageName || undefined, page: nextPage, page_size: pageSize });
    if (current === requestId) {
      const result = unwrap<{ items: ParseJob[]; total?: number; page?: number }>(response);
      jobs.value = result.items;
      total.value = result.total ?? result.items.length;
      page.value = result.page ?? nextPage;
    }
  } catch (cause) {
    if (current === requestId) error.value = cause instanceof Error ? cause.message : "历史解析结果读取失败";
  } finally { if (current === requestId) loading.value = false; }
}
watch(() => props.packageName, () => { if (expanded.value) void load(1); else { requestId++; jobs.value = []; total.value = 0; page.value = 1; } });
function toggleExpanded() { expanded.value = !expanded.value; if (expanded.value) void load(1); }
defineExpose({ load });
</script>

<style scoped>
.history-panel { display: grid; gap: 10px; }
.panel-header { display: flex; align-items: center; justify-content: space-between; }
.panel-header h3 { margin: 0; }
.history-actions { display: flex; gap: 6px; }
.history-pagination { display: flex; align-items: center; justify-content: center; gap: 10px; }
.history-list { display: grid; gap: 6px; max-height: 220px; overflow: auto; }
.history-list button { display: grid; gap: 4px; text-align: left; border: 1px solid var(--border-soft); border-radius: 6px; padding: 8px 10px; background: transparent; color: var(--text-primary); cursor: pointer; }
.history-list button.active { background: var(--hover-bg); border-color: var(--accent); }
.history-list small { color: var(--text-muted); }
.ghost { border: 1px solid var(--border-soft); border-radius: 6px; background: transparent; padding: 6px 10px; }
.empty-state, .feedback { margin: 0; color: var(--text-muted); }
.feedback.error { color: var(--error-text); }
</style>
