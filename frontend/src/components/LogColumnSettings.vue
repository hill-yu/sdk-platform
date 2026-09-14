<template>
  <section class="column-settings" aria-label="指标列配置">
    <div class="settings-header">
      <div>
        <h3>配置指标</h3>
        <p>拖动以外也可以使用上下按钮调整显示顺序；日期和包名为强制列。</p>
      </div>
      <span v-if="saveError" class="save-error" role="alert">{{ saveError }}</span>
    </div>

    <div class="column-groups">
      <div>
        <h4>可见列</h4>
        <ol class="column-list" data-testid="visible-columns">
          <li v-for="(column, index) in draftColumns" :key="column" :data-testid="`column-${column}-visible`">
            <span>{{ column }}</span>
            <span class="column-actions">
              <button
                :data-testid="`column-${column}-up`"
                type="button"
                :disabled="saving || index === 0"
                :aria-label="`上移 ${column}`"
                @click="move(column, -1)"
              >↑</button>
              <button
                :data-testid="`column-${column}-down`"
                type="button"
                :disabled="saving || index === draftColumns.length - 1"
                :aria-label="`下移 ${column}`"
                @click="move(column, 1)"
              >↓</button>
              <button
                :data-testid="`column-${column}-remove`"
                type="button"
                :disabled="saving || isRequired(column)"
                :aria-label="`移除 ${column}`"
                @click="remove(column)"
              >移除</button>
            </span>
          </li>
        </ol>
      </div>

      <div>
        <h4>隐藏列</h4>
        <ul class="column-list" data-testid="hidden-columns">
          <li v-for="column in hiddenColumns" :key="column" :data-testid="`column-${column}-hidden`">
            <span>{{ column }}</span>
            <button
              :data-testid="`column-add-${column}`"
              type="button"
              :disabled="saving"
              @click="add(column)"
            >添加</button>
          </li>
          <li v-if="!hiddenColumns.length" class="empty">没有隐藏列</li>
        </ul>
      </div>
    </div>

    <div class="settings-actions">
      <button data-testid="column-settings-reset" type="button" :disabled="saving" @click="reset">恢复默认</button>
      <button data-testid="column-settings-save" type="button" :disabled="saving" @click="save">保存</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";

const REQUIRED_COLUMNS = new Set(["date", "package_name"]);

const props = withDefaults(
  defineProps<{
    availableColumns: string[];
    defaultColumns: string[];
    modelValue: string[];
    saving?: boolean;
    saveError?: string | null;
  }>(),
  { saving: false, saveError: null },
);

const emit = defineEmits<{
  save: [columns: string[]];
}>();

function ensureRequired(columns: string[]) {
  const selected = columns.filter((column, index) => props.availableColumns.includes(column) && columns.indexOf(column) === index);
  const required = ["date", "package_name"].filter((column) => props.availableColumns.includes(column));
  return [...required, ...selected.filter((column) => !REQUIRED_COLUMNS.has(column))];
}

const draftColumns = ref<string[]>(ensureRequired(props.modelValue));
const committedSignature = ref(JSON.stringify(ensureRequired(props.modelValue)));

watch(
  () => props.modelValue,
  (value) => {
    const normalized = ensureRequired(value);
    const signature = JSON.stringify(normalized);
    if (signature !== committedSignature.value) {
      draftColumns.value = normalized;
      committedSignature.value = signature;
    }
  },
  { deep: true },
);

const hiddenColumns = computed(() => props.availableColumns.filter((column) => !draftColumns.value.includes(column)));

function isRequired(column: string) {
  return REQUIRED_COLUMNS.has(column);
}

function add(column: string) {
  if (!draftColumns.value.includes(column) && props.availableColumns.includes(column)) {
    draftColumns.value.push(column);
  }
}

function remove(column: string) {
  if (isRequired(column)) return;
  draftColumns.value = draftColumns.value.filter((item) => item !== column);
}

function move(column: string, direction: -1 | 1) {
  const index = draftColumns.value.indexOf(column);
  const nextIndex = index + direction;
  if (index < 0 || nextIndex < 0 || nextIndex >= draftColumns.value.length) return;
  const next = [...draftColumns.value];
  [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
  draftColumns.value = next;
}

function reset() {
  draftColumns.value = ensureRequired(props.defaultColumns);
}

function save() {
  emit("save", [...draftColumns.value]);
}
</script>

<style scoped>
.column-settings { display: grid; gap: 16px; }
.settings-header, .settings-actions, .column-actions { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
h3, h4, p { margin: 0; }
h3 { color: var(--text-primary); }
h4 { margin-bottom: 8px; color: var(--text-secondary); font-size: 12px; }
p, .empty { color: var(--text-secondary); font-size: 12px; }
.save-error { color: #ef8f82; font-size: 12px; }
.column-groups { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.column-list { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
.column-list li { display: flex; align-items: center; justify-content: space-between; gap: 8px; border: 1px solid var(--border-soft); border-radius: 8px; padding: 7px 9px; color: var(--text-primary); }
button { border: 1px solid var(--border-soft); border-radius: 7px; background: rgba(8, 13, 13, .5); color: var(--text-primary); padding: 5px 8px; cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .5; }
@media (max-width: 700px) { .column-groups { grid-template-columns: 1fr; } }
</style>
