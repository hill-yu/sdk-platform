<template>
  <section class="log-detail" aria-label="日志详情">
    <p v-if="!item" class="empty-state">请选择一条日志查看详情。</p>
    <template v-else>
      <dl class="detail-grid">
        <div v-for="field in fields" :key="field.label">
          <dt>{{ field.label }}</dt>
          <dd class="detail-value">{{ display(field.value) }}</dd>
        </div>
      </dl>
      <div class="extra-header">
        <h4>extra</h4>
        <button data-testid="copy-extra" class="ghost" type="button" @click="copyExtra">
          复制 extra
        </button>
      </div>
      <pre data-testid="log-extra">{{ display(item.payload.extra) }}</pre>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";

import type { EventItem } from "@/api/dashboard";

const props = defineProps<{ item: EventItem | null }>();
const emit = defineEmits<{ "copy-success": []; "copy-error": [message: string] }>();

const fields = computed(() => {
  if (!props.item) return [];
  return [
    { label: "时间", value: props.item.server_ts },
    { label: "包名", value: props.item.package_name },
    { label: "设备 ID", value: props.item.device_id },
    { label: "SDK 版本", value: props.item.sdk_version },
    { label: "level", value: props.item.payload.level },
    { label: "tag", value: props.item.payload.tag },
    { label: "message", value: props.item.payload.message },
  ];
});

function display(value: unknown): string {
  return value == null || value === "" ? "-" : String(value);
}

async function copyExtra(): Promise<void> {
  try {
    await navigator.clipboard.writeText(String(props.item?.payload.extra ?? ""));
    emit("copy-success");
  } catch (error) {
    emit("copy-error", error instanceof Error ? error.message : "复制失败");
  }
}
</script>

<style scoped>
.log-detail {
  min-width: 0;
}

.detail-grid {
  display: grid;
  gap: 14px;
  margin: 0;
}

.detail-grid div {
  display: grid;
  gap: 4px;
}

dt {
  color: var(--text-muted);
  font-size: 12px;
}

dd {
  margin: 0;
  word-break: break-word;
}

.extra-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 20px;
}

.extra-header h4 {
  margin: 0;
}

pre {
  max-height: 360px;
  overflow: auto;
  margin: 12px 0 0;
  padding: 14px;
  border-radius: 14px;
  background: rgba(0, 0, 0, 0.22);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: Consolas, "SFMono-Regular", monospace;
}

.ghost {
  padding: 8px 10px;
  border: 1px solid var(--border-soft);
  border-radius: 10px;
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.05);
}

.empty-state {
  color: var(--text-muted);
}
</style>
