<template>
  <div ref="root" class="package-select" :class="{ disabled }">
    <div v-if="multiple" class="selected-packages">
      <span v-for="name in selectedNames" :key="name" class="package-chip">
        {{ name }}
        <button :data-testid="removeTestId" type="button" :disabled="disabled" @click="remove(name)">×</button>
      </span>
    </div>
    <input
      v-model="keyword"
      :data-testid="inputTestId"
      type="text"
      :placeholder="placeholder"
      :disabled="disabled"
      role="combobox"
      :aria-expanded="open"
      @focus="openPicker"
      @keydown="onKeydown"
      @focusout="onFocusout"
    />
    <div v-if="open" class="package-options" role="listbox">
      <p v-if="loading" data-testid="package-select-loading">加载中…</p>
      <template v-else-if="error">
        <p data-testid="package-select-error" class="package-error">{{ error }}</p>
        <button data-testid="package-select-retry" type="button" @click="searchNow()">重试</button>
      </template>
      <p v-else-if="!options.length" data-testid="package-select-empty">暂无匹配包名</p>
      <template v-else>
        <button
          v-for="(name, index) in options"
          :key="name"
          :data-package="name"
          :data-testid="optionTestId"
          class="package-option"
          role="option"
          type="button"
          :class="{ highlighted: highlightedIndex === index }"
          :disabled="selectedNames.includes(name)"
          @mouseenter="highlightedIndex = index"
          @click="select(name)"
        >{{ name }}</button>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { searchLogPackages } from "@/api/logExports";

type PackageSearch = (keyword: string) => Promise<{ code: number; data: { items: string[] } }>;

const props = withDefaults(defineProps<{
  modelValue: string | string[];
  multiple?: boolean;
  placeholder?: string;
  disabled?: boolean;
  inputTestId?: string;
  optionTestId?: string;
  removeTestId?: string;
  searchPackages?: PackageSearch;
  allowFreeText?: boolean;
}>(), { multiple: false, placeholder: "搜索包名", disabled: false, inputTestId: "package-select-input", optionTestId: "package-select-option", removeTestId: "package-select-remove", allowFreeText: false });
const emit = defineEmits<{ "update:modelValue": [value: string | string[]] }>();

const root = ref<HTMLElement | null>(null);
const keyword = ref("");
const options = ref<string[]>([]);
const open = ref(false);
const loading = ref(false);
const error = ref("");
const highlightedIndex = ref(-1);
let timer: ReturnType<typeof setTimeout> | undefined;
let requestId = 0;
let suppressKeywordSearch = false;

const selectedNames = computed(() => props.multiple ? [...(props.modelValue as string[])] : (props.modelValue ? [props.modelValue as string] : []));
if (!props.multiple && typeof props.modelValue === "string") keyword.value = props.modelValue;

function searchNow(currentId = ++requestId) {
  if (timer) clearTimeout(timer);
  loading.value = true;
  error.value = "";
  const search = props.searchPackages ?? searchLogPackages;
  void search(keyword.value.trim()).then((response) => {
    if (currentId !== requestId) return;
    options.value = response.data.items;
    highlightedIndex.value = -1;
  }).catch((cause) => {
    if (currentId !== requestId) return;
    options.value = [];
    error.value = cause instanceof Error ? cause.message : "包名搜索失败";
  }).finally(() => {
    if (currentId === requestId) loading.value = false;
  });
}
function scheduleSearch() {
  if (timer) clearTimeout(timer);
  const currentId = ++requestId;
  options.value = [];
  highlightedIndex.value = -1;
  loading.value = true;
  error.value = "";
  timer = setTimeout(() => { timer = undefined; searchNow(currentId); }, 300);
}
function openPicker() { if (!props.disabled) { if (!props.multiple && keyword.value === props.modelValue) keyword.value = ""; open.value = true; scheduleSearch(); } }
function select(name: string) {
  if (!options.value.includes(name) || selectedNames.value.includes(name)) return;
  if (props.multiple) emit("update:modelValue", [...selectedNames.value, name]);
  else { emit("update:modelValue", name); suppressKeywordSearch = true; keyword.value = name; open.value = false; }
}
function remove(name: string) { if (props.multiple) emit("update:modelValue", selectedNames.value.filter((item) => item !== name)); }
function moveHighlight(direction: 1 | -1) {
  if (!options.value.length) return;
  let index = highlightedIndex.value;
  for (let attempt = 0; attempt < options.value.length; attempt += 1) {
    index = (index + direction + options.value.length) % options.value.length;
    if (!selectedNames.value.includes(options.value[index])) { highlightedIndex.value = index; return; }
  }
  highlightedIndex.value = -1;
}
function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") { cancelSearchAndRestore(); return; }
  if (!open.value || !options.value.length) return;
  if (event.key === "ArrowDown") { event.preventDefault(); moveHighlight(1); }
  else if (event.key === "ArrowUp") { event.preventDefault(); moveHighlight(-1); }
  else if (event.key === "Enter" && highlightedIndex.value >= 0 && !selectedNames.value.includes(options.value[highlightedIndex.value])) { event.preventDefault(); select(options.value[highlightedIndex.value]); }
}
function cancelSearchAndRestore() {
  if (timer) { clearTimeout(timer); timer = undefined; }
  ++requestId;
  open.value = false;
  loading.value = false;
  error.value = "";
  options.value = [];
  highlightedIndex.value = -1;
  suppressKeywordSearch = true;
  keyword.value = props.multiple ? "" : (typeof props.modelValue === "string" ? props.modelValue : "");
}
function onFocusout(event: FocusEvent) {
  const nextTarget = event.relatedTarget as Node | null;
  if (root.value && nextTarget && root.value.contains(nextTarget)) return;
  cancelSearchAndRestore();
}
function onDocumentClick(event: MouseEvent) {
  if (root.value && !root.value.contains(event.target as Node)) {
    cancelSearchAndRestore();
  }
}
document.addEventListener("click", onDocumentClick);
watch(keyword, () => {
  if (suppressKeywordSearch) { suppressKeywordSearch = false; return; }
  if (props.allowFreeText && !props.multiple) emit("update:modelValue", keyword.value.trim());
  if (!props.disabled && open.value) {
    scheduleSearch();
  }
});
watch(() => props.modelValue, (value) => { if (!open.value && !props.multiple) keyword.value = typeof value === "string" ? value : ""; }, { deep: true });
onBeforeUnmount(() => { if (timer) clearTimeout(timer); ++requestId; document.removeEventListener("click", onDocumentClick); });
</script>

<style scoped>
.package-select { position: relative; display: grid; gap: 6px; min-width: 220px; }
.package-select > input { width: 100%; box-sizing: border-box; }
.selected-packages { display: flex; flex-wrap: wrap; gap: 6px; }
.package-chip { padding: 4px 8px; border-radius: 6px; background: var(--warning-bg); }
.package-chip button { border: 0; background: transparent; padding: 0 2px; cursor: pointer; }
.package-options { position: absolute; z-index: 20; top: 100%; left: 0; right: 0; display: grid; gap: 4px; max-height: 240px; overflow: auto; padding: 6px; border: 1px solid var(--border-soft); border-radius: 6px; background: var(--panel-bg); box-shadow: var(--panel-shadow); }
.package-options .package-option { appearance: none; width: 100%; border: 1px solid transparent; border-radius: 5px; text-align: left; color: var(--text-primary); background: var(--panel-bg); padding: 8px 10px; cursor: pointer; }
.package-options .package-option:hover, .package-options .package-option.highlighted { border-color: var(--hover-border); background: var(--hover-bg); }
.package-options .package-option:disabled { border-color: var(--disabled-border); color: var(--disabled-text); background: var(--disabled-bg); cursor: not-allowed; opacity: 1; }
.package-options p { margin: 4px 6px; color: var(--text-muted); font-size: 12px; }
.package-error { color: var(--error-text) !important; }
</style>
