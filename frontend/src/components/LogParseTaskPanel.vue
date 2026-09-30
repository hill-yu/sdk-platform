<template>
  <section class="task-panel" data-testid="parse-task-panel">
    <div class="task-copy">
      <h4>解析任务</h4>
      <p>按当前北京时间范围生成或刷新结构化解析结果。</p>
    </div>
    <div class="task-actions">
      <button v-if="!active" data-testid="start-parse" type="button" :disabled="disabled || !scope.package_name" @click="start">开始解析</button>
      <button v-else data-testid="cancel-parse" type="button" class="ghost" :disabled="cancelling" @click="cancel">取消任务</button>
    </div>
    <p v-if="job" data-testid="parse-status" class="task-status">
      状态：{{ statusLabel(job.status) }} · {{ job.processed_count }} / {{ job.total_count }} 条
    </p>
    <p v-if="error" data-testid="parse-error" class="task-error">{{ error }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";

import { cancelParseJob, getParseJob, postParseJob } from "@/api/logMetrics";
import type { LogMetricScope, ParseJob } from "@/api/logMetrics";

const props = withDefaults(defineProps<{ scope: LogMetricScope; disabled?: boolean }>(), { disabled: false });
const emit = defineEmits<{ refresh: []; status: [job: ParseJob] }>();

const job = ref<ParseJob | null>(null);
const error = ref("");
const cancelling = ref(false);
let timer: ReturnType<typeof setTimeout> | null = null;

const active = computed(() => job.value?.status === "pending" || job.value?.status === "running");

function unwrap<T>(response: unknown): T {
  let value = response && typeof response === "object" && "data" in response ? (response as { data?: unknown }).data : response;
  if (value && typeof value === "object" && "code" in value && "data" in value) value = (value as { data: unknown }).data;
  return value as T;
}

function clearTimer() {
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
}

function schedulePoll() {
  clearTimer();
  if (!active.value || !job.value) return;
  timer = setTimeout(() => { timer = null; void poll(); }, 1000);
}

function finish(nextJob: ParseJob) {
  job.value = nextJob;
  emit("status", nextJob);
  if (nextJob.status === "success") emit("refresh");
  schedulePoll();
}

async function start() {
  if (active.value || props.disabled) return;
  error.value = "";
  try {
    const response = await postParseJob(props.scope);
    finish(unwrap<ParseJob>(response));
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "解析任务创建失败";
  }
}

async function poll() {
  if (!job.value || !active.value) return;
  try {
    const response = await getParseJob(job.value.id);
    finish(unwrap<ParseJob>(response));
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "解析任务状态读取失败";
    schedulePoll();
  }
}

async function cancel() {
  if (!job.value || !active.value || cancelling.value) return;
  cancelling.value = true;
  clearTimer();
  try {
    const response = await cancelParseJob(job.value.id);
    finish(unwrap<ParseJob>(response));
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "解析任务取消失败";
    schedulePoll();
  } finally {
    cancelling.value = false;
  }
}

function statusLabel(status: ParseJob["status"]) {
  return { pending: "排队中", running: "解析中", success: "已完成", failed: "失败", cancelled: "已取消" }[status];
}

onBeforeUnmount(clearTimer);
</script>

<style scoped>
.task-panel { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px; border: 1px solid var(--border-soft); border-radius: 10px; background: rgba(8, 13, 13, .26); }
.task-copy h4, .task-copy p { margin: 0; }
.task-copy p, .task-status { color: var(--text-secondary); font-size: 12px; }
.task-actions { display: flex; gap: 8px; flex: none; }
button { border: 1px solid var(--border-soft); border-radius: 8px; background: var(--accent, #b6622b); color: var(--text-primary); padding: 8px 14px; cursor: pointer; }
button.ghost { background: transparent; }
button:disabled { cursor: not-allowed; opacity: .55; }
.task-status { margin: 0; }
.task-error { color: var(--danger, #d9785d); font-size: 12px; }
</style>
