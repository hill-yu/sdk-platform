<template>
  <div class="package-picker">
    <div class="selected-packages">
      <span v-for="name in modelValue" :key="name" class="package-chip">
        {{ name }}
        <button data-testid="remove-package" type="button" @click="remove(name)">×</button>
      </span>
    </div>
    <input
      v-model="keyword"
      data-testid="package-search"
      type="text"
      placeholder="检索要导出的包名"
      @focus="open = true"
    />
    <div v-if="open && options.length" class="package-options">
      <button
        v-for="name in options"
        :key="name"
        data-testid="package-option"
        type="button"
        :disabled="modelValue.includes(name)"
        @click="add(name)"
      >{{ name }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { searchLogPackages } from "@/api/logExports";

const props = defineProps<{ modelValue: string[] }>();
const emit = defineEmits<{ (event: "update:modelValue", value: string[]): void }>();
const keyword = ref("");
const options = ref<string[]>([]);
const open = ref(false);
let timer: ReturnType<typeof setTimeout> | undefined;
let latestSearch = 0;

watch(keyword, (value) => {
  if (timer) clearTimeout(timer);
  const searchId = ++latestSearch;
  timer = setTimeout(async () => {
    const response = await searchLogPackages(value);
    if (searchId !== latestSearch) return;
    options.value = response.data.items;
    open.value = true;
  }, 300);
});
function add(name: string) {
  if (!props.modelValue.includes(name)) emit("update:modelValue", [...props.modelValue, name]);
}
function remove(name: string) {
  emit("update:modelValue", props.modelValue.filter((item) => item !== name));
}
onBeforeUnmount(() => { if (timer) clearTimeout(timer); });
</script>

<style scoped>
.package-picker { position: relative; display: grid; gap: 8px; min-width: 360px; }
.selected-packages { display: flex; flex-wrap: wrap; gap: 6px; }
.package-chip { padding: 5px 8px; border-radius: 10px; background: rgba(214,140,69,.18); }
.package-chip button { padding: 0 3px; border: 0; background: transparent; }
.package-options { position: absolute; z-index: 5; top: 100%; width: 100%; display: grid; padding: 6px; border: 1px solid var(--border-soft); border-radius: 12px; background: var(--panel-bg); }
.package-options button { text-align: left; }
</style>
