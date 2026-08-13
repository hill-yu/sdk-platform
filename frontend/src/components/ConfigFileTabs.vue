<template>
  <div class="config-file-tabs" role="tablist" aria-label="配置文件">
    <button
      v-for="file in configFiles"
      :key="file"
      type="button"
      role="tab"
      data-testid="config-file-tab"
      :aria-selected="modelValue === file"
      :class="{ active: modelValue === file }"
      @click="emit('update:modelValue', file)"
    >
      {{ file }}
    </button>
  </div>
</template>

<script setup lang="ts">
export type ConfigFileName = "mainConfig" | "newTouchConfig" | "newTextRuleConfig";

defineProps<{ modelValue: ConfigFileName }>();
const emit = defineEmits<{ "update:modelValue": [value: ConfigFileName] }>();
const configFiles: ConfigFileName[] = ["mainConfig", "newTouchConfig", "newTextRuleConfig"];
</script>

<style scoped>
.config-file-tabs { display: flex; gap: 8px; margin: 14px 0; }
button { border-radius: 10px; border: 1px solid var(--border-soft); background: rgba(8, 13, 13, .5); color: var(--text-primary); padding: 9px 12px; }
button.active { border-color: #d68c45; background: rgba(182, 98, 43, .35); }
</style>
