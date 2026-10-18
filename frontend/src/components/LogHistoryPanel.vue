<template>
  <section class="panel history-panel" data-testid="history-panel">
    <div class="panel-header"><h3>历史解析结果</h3><button class="ghost" type="button" :disabled="loading" @click="load">刷新</button></div>
    <p v-if="error" data-testid="history-error" class="feedback error">{{ error }}</p>
    <p v-else-if="loading" data-testid="history-loading" class="empty-state">加载中…</p>
    <p v-else-if="!jobs.length" data-testid="history-empty" class="empty-state">暂无可读取的历史解析结果。</p>
    <div v-else class="history-list">
      <button v-for="job in jobs" :key="job.id" type="button" data-testid="history-job" :disabled="job.historical_available === false" :class="{ active: selectedJobId === job.id }" @click="job.historical_available !== false && emit('select', job)">
        <span>#{{ job.id }} · {{ job.package_name }} · {{ job.status }}</span><small>{{ job.range_start }} 至 {{ job.range_end }}{{ job.error_summary ? ` · ${job.error_summary}` : "" }}</small>
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { getHistoricalParseJobs } from "@/api/logMetrics";
import type { ParseJob } from "@/api/logMetrics";

const props = withDefaults(defineProps<{ packageName?: string; selectedJobId?: number | null }>(), { packageName: "", selectedJobId: null });
const emit = defineEmits<{ select: [job: ParseJob] }>();
const jobs = ref<ParseJob[]>([]);
const loading = ref(false);
const error = ref("");
let requestId = 0;
function unwrap<T>(response: unknown): T {
  let value = response && typeof response === "object" && "data" in response ? (response as { data?: unknown }).data : response;
  if (value && typeof value === "object" && "code" in value && "data" in value) value = (value as { data: unknown }).data;
  return value as T;
}
async function load() {
  const current = ++requestId;
  loading.value = true; error.value = ""; jobs.value = [];
  try {
    const response = await getHistoricalParseJobs({ package_name: props.packageName || undefined, page: 1, page_size: 10 });
    if (current === requestId) jobs.value = unwrap<{ items: ParseJob[] }>(response).items;
  } catch (cause) {
    if (current === requestId) error.value = cause instanceof Error ? cause.message : "历史解析结果读取失败";
  } finally { if (current === requestId) loading.value = false; }
}
watch(() => props.packageName, () => { void load(); });
onMounted(() => { void load(); });
defineExpose({ load });
</script>

<style scoped>
.history-panel { display: grid; gap: 10px; }
.panel-header { display: flex; align-items: center; justify-content: space-between; }
.panel-header h3 { margin: 0; }
.history-list { display: grid; gap: 6px; max-height: 220px; overflow: auto; }
.history-list button { display: grid; gap: 4px; text-align: left; border: 1px solid var(--border-soft); border-radius: 6px; padding: 8px 10px; background: transparent; color: var(--text-primary); cursor: pointer; }
.history-list button.active { background: var(--hover-bg); border-color: var(--accent); }
.history-list small { color: var(--text-muted); }
.ghost { border: 1px solid var(--border-soft); border-radius: 6px; background: transparent; padding: 6px 10px; }
.empty-state, .feedback { margin: 0; color: var(--text-muted); }
.feedback.error { color: var(--error-text); }
</style>
