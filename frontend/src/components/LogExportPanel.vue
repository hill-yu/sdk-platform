<template>
  <section class="export-panel">
    <label class="export-mode-label">导出模式
      <select data-testid="export-mode" :value="exportMode" :disabled="modeLocked" @change="changeExportMode">
        <option value="raw">原始日志</option>
        <option value="h1">H1 结构化</option>
      </select>
    </label>
    <span v-if="exportMode === 'h1'" data-testid="h1-export-note" class="export-note">有 H1 按条拆行，无 H1 保留原始 extra</span>
    <PackageMultiSelect v-if="!props.packageName" v-model="packageNames" />
    <span v-else data-testid="export-package">导出包名：{{ props.packageName }}</span>
    <button data-testid="export-button" class="primary" type="button" :disabled="!effectivePackageNames.length || modeLocked" @click="startExport">
      {{ submitting ? "正在创建任务" : "批量导出 CSV" }}
    </button>
    <span v-if="currentJob">状态：{{ statusText }}</span>
    <span v-if="currentJob?.status === 'success'">{{ currentJob.row_count }} 条</span>
    <button v-if="currentJob?.status === 'success'" data-testid="download-button" type="button" @click="download">下载 CSV</button>
    <span v-if="error" class="export-error">{{ error }}</span>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import type { LogLevel } from "@/api/dashboard";
import { createLogExport, downloadLogExport, getLogExport } from "@/api/logExports";
import type { LogExportJob } from "@/api/logExports";
import PackageMultiSelect from "@/components/PackageMultiSelect.vue";

const props = defineProps<{
  packageName: string;
  sdkVersion: string;
  deviceId: string;
  logLevel: "" | LogLevel;
  dateFrom: string;
  hourFrom?: string;
  dateTo: string;
  hourTo?: string;
}>();
const packageNames = ref<string[]>([]);
const effectivePackageNames = computed(() => props.packageName ? [props.packageName] : packageNames.value);
const currentJob = ref<LogExportJob | null>(null);
const submitting = ref(false);
const exportMode = ref<"raw" | "h1">("raw");
const error = ref("");
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
let generation = 0;
const statusText = computed(() => ({ pending: "等待处理", running: "生成中", success: "已完成", failed: "失败" }[currentJob.value?.status || "pending"]));
const modeLocked = computed(() => submitting.value || currentJob.value?.status === "pending" || currentJob.value?.status === "running");
function changeExportMode(event: Event) {
  if (modeLocked.value) return;
  exportMode.value = (event.target as HTMLSelectElement).value as "raw" | "h1";
}

function clearPollTimer() {
  if (timer) {
    clearTimeout(timer);
    timer = undefined;
  }
}

function isCurrent(requestGeneration: number, expectedJobId?: string) {
  return !disposed
    && generation === requestGeneration
    && (expectedJobId === undefined || currentJob.value?.id === expectedJobId);
}

function schedulePoll(requestGeneration: number, expectedJobId: string) {
  clearPollTimer();
  if (!isCurrent(requestGeneration, expectedJobId)) return;
  if (currentJob.value?.status !== "pending" && currentJob.value?.status !== "running") return;
  timer = setTimeout(() => {
    timer = undefined;
    if (isCurrent(requestGeneration, expectedJobId)) void pollJob(requestGeneration, expectedJobId);
  }, 2000);
}

async function pollJob(requestGeneration: number, expectedJobId: string) {
  if (!isCurrent(requestGeneration, expectedJobId)) return;
  try {
    const response = await getLogExport(expectedJobId);
    if (!isCurrent(requestGeneration, expectedJobId) || response.data.id !== expectedJobId) return;
    const previousMode = currentJob.value?.export_mode;
    currentJob.value = { ...response.data, export_mode: response.data.export_mode ?? previousMode };
    if (response.data.status === "failed") error.value = response.data.error_message || "导出失败";
    else if (response.data.status === "success") error.value = "";
    schedulePoll(requestGeneration, expectedJobId);
  } catch (caught) {
    if (!isCurrent(requestGeneration, expectedJobId)) return;
    error.value = caught instanceof Error ? caught.message : "查询导出状态失败";
    schedulePoll(requestGeneration, expectedJobId);
  }
}
async function startExport() {
  if (disposed || submitting.value || modeLocked.value) return;
  const requestGeneration = ++generation;
  clearPollTimer();
  const selectedPackageNames = [...effectivePackageNames.value];
  const selectedMode = exportMode.value;
  submitting.value = true; error.value = "";
  try {
    const response = await createLogExport({
      package_names: selectedPackageNames,
      export_mode: selectedMode,
      sdk_version: props.sdkVersion || undefined,
      device_id: props.deviceId || undefined,
      log_level: props.logLevel || undefined,
      date_from: props.dateFrom || undefined,
      hour_from: props.hourFrom ? Number(props.hourFrom) : undefined,
      date_to: props.dateTo || undefined,
      hour_to: props.hourTo ? Number(props.hourTo) : undefined,
    });
    if (!isCurrent(requestGeneration)) return;
    currentJob.value = { ...response.data, row_count: 0, export_mode: selectedMode };
    schedulePoll(requestGeneration, response.data.id);
  } catch (caught) {
    if (isCurrent(requestGeneration)) error.value = caught instanceof Error ? caught.message : "创建导出任务失败";
  } finally {
    if (!disposed && generation === requestGeneration) submitting.value = false;
  }
}
async function download() {
  const job = currentJob.value;
  if (!job) return;
  const requestGeneration = generation;
  const expectedJobId = job.id;
  try {
    error.value = "";
    const response = await downloadLogExport(expectedJobId);
    if (!isCurrent(requestGeneration, expectedJobId)) return;
    const url = URL.createObjectURL(response as unknown as Blob);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `sdk-logs-${expectedJobId}.csv`; anchor.click();
    URL.revokeObjectURL(url);
  } catch (caught) {
    if (isCurrent(requestGeneration, expectedJobId)) error.value = caught instanceof Error ? caught.message : "下载导出文件失败";
  }
}
onBeforeUnmount(() => {
  disposed = true;
  generation += 1;
  clearPollTimer();
});
</script>

<style scoped>
.export-panel { display: flex; flex-wrap: wrap; align-items: end; gap: 10px; margin-top: 14px; }
.export-mode-label { display: grid; gap: 5px; color: var(--text-secondary); font-size: 12px; }
.export-mode-label select { border: 1px solid var(--border-soft); border-radius: 8px; color: var(--text-primary); background: rgba(255, 255, 255, .05); padding: 8px 10px; }
.export-mode-label select:disabled { cursor: not-allowed; opacity: .55; }
.export-note { color: var(--text-secondary); font-size: 12px; }
.export-error { color: #ffb0a8; }
</style>
