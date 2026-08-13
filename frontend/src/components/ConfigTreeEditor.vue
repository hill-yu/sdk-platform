<template>
  <section class="config-tree-editor" aria-label="配置树编辑器">
    <ConfigTreeNode
      node-key="root"
      :value="modelValue"
      :path="[]"
      parent-kind="root"
      :disabled="disabled"
      :node-error="errorForPath([])"
      :error-for-path="errorForPath"
      @add-child="addChild"
      @add-sibling="addSibling"
      @rename="renameField"
      @replace="replaceNode"
      @remove="removeNode"
      @duplicate="duplicateNode"
      @move="moveNode"
    />
  </section>
</template>

<script setup lang="ts">
import { ref } from "vue";

import ConfigTreeNode from "@/components/ConfigTreeNode.vue";
import {
  addObjectField,
  appendArrayItem,
  duplicateArrayItem,
  getAtPath,
  jsonTypeOf,
  moveArrayItem,
  removeAtPath,
  renameObjectField,
  replaceAtPath,
  type JsonValue,
  type TreePath,
} from "@/utils/configTree";

type PathPayload = { path: TreePath };
type AddPayload = PathPayload & { key?: string; value: JsonValue };
type RenamePayload = PathPayload & { key: string };
type ReplacePayload = PathPayload & { value: JsonValue };
type MovePayload = PathPayload & { direction: -1 | 1 };

const props = withDefaults(defineProps<{ modelValue: JsonValue; disabled?: boolean }>(), {
  disabled: false,
});
const emit = defineEmits<{ "update:modelValue": [value: JsonValue] }>();
const errors = ref<Record<string, string>>({});

function pathKey(path: TreePath): string {
  return JSON.stringify(path);
}

function errorForPath(path: TreePath): string {
  return errors.value[pathKey(path)] ?? "";
}

function run(path: TreePath, operation: () => JsonValue): void {
  if (props.disabled) return;
  try {
    const value = operation();
    const key = pathKey(path);
    if (errors.value[key]) {
      const next = { ...errors.value };
      delete next[key];
      errors.value = next;
    }
    emit("update:modelValue", value);
  } catch (error) {
    errors.value = {
      ...errors.value,
      [pathKey(path)]: error instanceof Error ? error.message : "操作失败",
    };
  }
}

function isNonEmptyContainer(value: JsonValue): boolean {
  return (Array.isArray(value) && value.length > 0)
    || (value !== null && typeof value === "object" && Object.keys(value).length > 0);
}

function confirmDestructive(message: string): boolean {
  return window.confirm(message);
}

function addChild(payload: AddPayload): void {
  run(payload.path, () => {
    const parent = getAtPath(props.modelValue, payload.path);
    if (Array.isArray(parent)) return appendArrayItem(props.modelValue, payload.path, payload.value);
    return addObjectField(props.modelValue, payload.path, payload.key ?? "", payload.value);
  });
}

function addSibling(payload: AddPayload): void {
  const parentPath = payload.path.slice(0, -1);
  run(payload.path, () => addObjectField(props.modelValue, parentPath, payload.key ?? "", payload.value));
}

function renameField(payload: RenamePayload): void {
  run(payload.path, () => renameObjectField(props.modelValue, payload.path, payload.key));
}

function replaceNode(payload: ReplacePayload): void {
  const current = getAtPath(props.modelValue, payload.path);
  if (
    isNonEmptyContainer(current)
    && jsonTypeOf(payload.value) !== jsonTypeOf(current)
    && !confirmDestructive("更改非空容器类型会删除所有子项，确定继续吗？")
  ) return;
  run(payload.path, () => replaceAtPath(props.modelValue, payload.path, payload.value));
}

function removeNode(payload: PathPayload): void {
  const current = getAtPath(props.modelValue, payload.path);
  if (isNonEmptyContainer(current) && !confirmDestructive("删除非空容器会删除所有子项，确定继续吗？")) return;
  run(payload.path, () => removeAtPath(props.modelValue, payload.path));
}

function duplicateNode(payload: PathPayload): void {
  run(payload.path, () => duplicateArrayItem(props.modelValue, payload.path));
}

function moveNode(payload: MovePayload): void {
  run(payload.path, () => moveArrayItem(props.modelValue, payload.path, payload.direction));
}
</script>

<style scoped>
.config-tree-editor { min-width: 0; overflow-x: auto; }
</style>
