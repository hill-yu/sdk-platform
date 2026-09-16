<template>
  <section class="export-panel">
    <PackageMultiSelect v-model="packageNames" />
    <button data-testid="export-button" class="primary" type="button" :disabled="!packageNames.length || submitting" @click="startExport">
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

const props = defineProps<{ deviceId: string; logLevel: "" | LogLevel; dateFrom: string; dateTo: string }>();
const packageNames = ref<string[]>([]);
const currentJob = ref<LogExportJob | null>(null);
const submitting = ref(false);
const error = ref("");
let timer: ReturnType<typeof setTimeout> | undefined;
const statusText = computed(() => ({ pending: "等待处理", running: "生成中", success: "已完成", failed: "失败" }[currentJob.value?.status || "pending"]));

async function pollJob() {
  if (!currentJob.value) return;
  try {
    const response = await getLogExport(currentJob.value.id);
    currentJob.value = response.data;
    if (response.data.status === "pending" || response.data.status === "running") timer = setTimeout(pollJob, 2000);
    else if (response.data.status === "failed") error.value = response.data.error_message || "导出失败";
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "查询导出状态失败";
    if (currentJob.value?.status === "pending" || currentJob.value?.status === "running") timer = setTimeout(pollJob, 2000);
  }
}
async function startExport() {
  submitting.value = true; error.value = "";
  try {
    const response = await createLogExport({
      package_names: packageNames.value,
      device_id: props.deviceId || undefined,
      log_level: props.logLevel || undefined,
      date_from: props.dateFrom || undefined,
      date_to: props.dateTo || undefined,
    });
    currentJob.value = { ...response.data, row_count: 0 };
    timer = setTimeout(pollJob, 2000);
  } catch (caught) { error.value = caught instanceof Error ? caught.message : "创建导出任务失败"; }
  finally { submitting.value = false; }
}
async function download() {
  if (!currentJob.value) return;
  try {
    error.value = "";
    const response = await downloadLogExport(currentJob.value.id);
    const url = URL.createObjectURL(response as unknown as Blob);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `sdk-logs-${currentJob.value.id}.csv`; anchor.click();
    URL.revokeObjectURL(url);
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "下载导出文件失败";
  }
}
onBeforeUnmount(() => { if (timer) clearTimeout(timer); });
</script>

<style scoped>
.export-panel { display: flex; flex-wrap: wrap; align-items: end; gap: 10px; margin-top: 14px; }
.export-error { color: #ffb0a8; }
</style>
