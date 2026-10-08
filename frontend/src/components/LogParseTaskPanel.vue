<template>
  <section class="task-panel" data-testid="parse-task-panel">
    <div class="task-copy">
      <h4>解析任务</h4>
      <p>按当前北京时间范围生成或刷新结构化解析结果。</p>
    </div>
    <div class="task-actions">
      <button v-if="!activeJob" data-testid="start-parse" type="button" :disabled="disabled || starting || cancelling || !draftScope.package_name" @click="requestParse">{{ starting ? "创建中…" : "开始解析" }}</button>
      <button v-if="activeJob" data-testid="cancel-parse" class="ghost" type="button" :disabled="cancelling" @click="requestCancel">{{ cancelling ? "取消中…" : "取消任务" }}</button>
    </div>
    <p v-if="job" data-testid="parse-status" class="task-status">状态：{{ statusLabel(job.status) }} · {{ job.processed_count }} / {{ job.total_count }} 条</p>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";

import type { LogMetricScope, ParseJob } from "@/api/logMetrics";

const props = withDefaults(defineProps<{
  draftScope: LogMetricScope;
  appliedScope?: LogMetricScope | null;
  job?: ParseJob | null;
  disabled?: boolean;
  starting?: boolean;
  cancelling?: boolean;
}>(), { appliedScope: null, job: null, disabled: false, starting: false, cancelling: false });
const emit = defineEmits<{ "request-parse": [snapshot: LogMetricScope]; "request-cancel": [jobId: number] }>();

const activeJob = computed(() => props.job?.status === "pending" || props.job?.status === "running");
const active = computed(() => props.starting || activeJob.value);

function requestParse() {
  if (props.disabled || props.starting || props.cancelling || active.value || !props.draftScope.package_name) return;
  emit("request-parse", { ...props.draftScope });
}

function requestCancel() {
  if (props.cancelling || !props.job || !active.value) return;
  emit("request-cancel", props.job.id);
}

function statusLabel(status: ParseJob["status"]) { return { pending: "排队中", running: "解析中", success: "已完成", failed: "失败", cancelled: "已取消" }[status]; }
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
