<script setup lang="ts">
import PackageSelect from "@/components/PackageSelect.vue";

defineProps<{ modelValue: string[] }>();
defineEmits<{ "update:modelValue": [value: string[]] }>();
</script>

<template>
  <PackageSelect
    :model-value="modelValue"
    :multiple="true"
    input-test-id="package-search"
    option-test-id="package-option"
    remove-test-id="remove-package"
    placeholder="检索要导出的包名"
    @update:model-value="$emit('update:modelValue', $event as string[])"
  />
</template>
