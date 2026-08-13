<template>
  <section class="config-tree-editor" aria-label="配置树编辑器">
    <ConfigTreeNode
      node-key="root"
      :value="modelValue"
      :identity="identity"
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
import { ref, toRaw, watch } from "vue";

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
interface NodeIdentity {
  id: number;
  children: Record<string, NodeIdentity> | NodeIdentity[] | null;
}

const props = withDefaults(defineProps<{ modelValue: JsonValue; disabled?: boolean }>(), {
  disabled: false,
});
const emit = defineEmits<{ "update:modelValue": [value: JsonValue] }>();
const errors = ref<Record<number, string>>({});
let nextIdentity = 0;

function createIdentity(value: JsonValue): NodeIdentity {
  const id = nextIdentity++;
  if (Array.isArray(value)) {
    return { id, children: value.map(createIdentity) };
  }
  if (value !== null && typeof value === "object") {
    return {
      id,
      children: Object.fromEntries(Object.entries(value).map(([key, child]) => [key, createIdentity(child)])),
    };
  }
  return { id, children: null };
}

const identity = ref<NodeIdentity>(createIdentity(props.modelValue));
let pendingUpdate: { value: JsonValue; identity: NodeIdentity } | null = null;

watch(() => props.modelValue, (value) => {
  if (pendingUpdate?.value === toRaw(value)) {
    identity.value = pendingUpdate.identity;
  } else {
    identity.value = createIdentity(value);
  }
  pendingUpdate = null;
}, { flush: "sync" });

function errorForPath(path: TreePath): string {
  return errors.value[identityAtPath(identity.value, path).id] ?? "";
}

function identityAtPath(root: NodeIdentity, path: TreePath): NodeIdentity {
  return path.reduce((current, segment) => {
    if (current.children === null) throw new Error(`UI 节点路径无效: ${JSON.stringify(path)}`);
    return Array.isArray(current.children)
      ? current.children[segment as number]
      : current.children[segment as string];
  }, root);
}

function replaceIdentityAtPath(root: NodeIdentity, path: TreePath, replacement: NodeIdentity): NodeIdentity {
  if (path.length === 0) return replacement;
  const [segment, ...rest] = path;
  if (root.children === null) throw new Error(`UI 节点路径无效: ${JSON.stringify(path)}`);
  if (Array.isArray(root.children)) {
    const children = root.children.slice();
    children[segment as number] = replaceIdentityAtPath(children[segment as number], rest, replacement);
    return { ...root, children };
  }
  return {
    ...root,
    children: {
      ...root.children,
      [segment as string]: replaceIdentityAtPath(root.children[segment as string], rest, replacement),
    },
  };
}

function updateIdentityAtPath(
  root: NodeIdentity,
  path: TreePath,
  update: (node: NodeIdentity) => NodeIdentity,
): NodeIdentity {
  return replaceIdentityAtPath(root, path, update(identityAtPath(root, path)));
}

function run(
  path: TreePath,
  operation: () => JsonValue,
  updateIdentity: (root: NodeIdentity) => NodeIdentity = (root) => root,
): void {
  if (props.disabled) return;
  const targetIdentity = identityAtPath(identity.value, path).id;
  try {
    const value = operation();
    if (errors.value[targetIdentity]) {
      const next = { ...errors.value };
      delete next[targetIdentity];
      errors.value = next;
    }
    pendingUpdate = { value, identity: updateIdentity(identity.value) };
    emit("update:modelValue", value);
  } catch (error) {
    errors.value = {
      ...errors.value,
      [targetIdentity]: error instanceof Error ? error.message : "操作失败",
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
  }, (root) => updateIdentityAtPath(root, payload.path, (parent) => {
    if (Array.isArray(parent.children)) {
      return { ...parent, children: [...parent.children, createIdentity(payload.value)] };
    }
    return {
      ...parent,
      children: { ...(parent.children as Record<string, NodeIdentity>), [payload.key ?? ""]: createIdentity(payload.value) },
    };
  }));
}

function addSibling(payload: AddPayload): void {
  const parentPath = payload.path.slice(0, -1);
  run(
    payload.path,
    () => addObjectField(props.modelValue, parentPath, payload.key ?? "", payload.value),
    (root) => updateIdentityAtPath(root, parentPath, (parent) => ({
      ...parent,
      children: { ...(parent.children as Record<string, NodeIdentity>), [payload.key ?? ""]: createIdentity(payload.value) },
    })),
  );
}

function renameField(payload: RenamePayload): void {
  const parentPath = payload.path.slice(0, -1);
  const oldKey = payload.path.at(-1) as string;
  run(
    payload.path,
    () => renameObjectField(props.modelValue, payload.path, payload.key),
    (root) => updateIdentityAtPath(root, parentPath, (parent) => {
      const children = parent.children as Record<string, NodeIdentity>;
      return {
        ...parent,
        children: Object.fromEntries(Object.entries(children).map(([key, child]) => [key === oldKey ? payload.key : key, child])),
      };
    }),
  );
}

function replaceNode(payload: ReplacePayload): void {
  const current = getAtPath(props.modelValue, payload.path);
  if (
    isNonEmptyContainer(current)
    && jsonTypeOf(payload.value) !== jsonTypeOf(current)
    && !confirmDestructive("更改非空容器类型会删除所有子项，确定继续吗？")
  ) return;
  run(
    payload.path,
    () => replaceAtPath(props.modelValue, payload.path, payload.value),
    jsonTypeOf(payload.value) === jsonTypeOf(current)
      ? (root) => root
      : (root) => replaceIdentityAtPath(root, payload.path, createIdentity(payload.value)),
  );
}

function removeNode(payload: PathPayload): void {
  const current = getAtPath(props.modelValue, payload.path);
  if (isNonEmptyContainer(current) && !confirmDestructive("删除非空容器会删除所有子项，确定继续吗？")) return;
  const parentPath = payload.path.slice(0, -1);
  const segment = payload.path.at(-1)!;
  run(
    payload.path,
    () => removeAtPath(props.modelValue, payload.path),
    (root) => updateIdentityAtPath(root, parentPath, (parent) => {
      if (Array.isArray(parent.children)) {
        const children = parent.children.slice();
        children.splice(segment as number, 1);
        return { ...parent, children };
      }
      const children = Object.fromEntries(
        Object.entries(parent.children as Record<string, NodeIdentity>).filter(([key]) => key !== segment),
      );
      return { ...parent, children };
    }),
  );
}

function duplicateNode(payload: PathPayload): void {
  const parentPath = payload.path.slice(0, -1);
  const index = payload.path.at(-1) as number;
  run(
    payload.path,
    () => duplicateArrayItem(props.modelValue, payload.path),
    (root) => updateIdentityAtPath(root, parentPath, (parent) => {
      const children = (parent.children as NodeIdentity[]).slice();
      children.splice(index + 1, 0, createIdentity(getAtPath(props.modelValue, payload.path)));
      return { ...parent, children };
    }),
  );
}

function moveNode(payload: MovePayload): void {
  const parentPath = payload.path.slice(0, -1);
  const index = payload.path.at(-1) as number;
  run(
    payload.path,
    () => moveArrayItem(props.modelValue, payload.path, payload.direction),
    (root) => updateIdentityAtPath(root, parentPath, (parent) => {
      const children = (parent.children as NodeIdentity[]).slice();
      const destination = index + payload.direction;
      [children[index], children[destination]] = [children[destination], children[index]];
      return { ...parent, children };
    }),
  );
}
</script>

<style scoped>
.config-tree-editor { min-width: 0; overflow-x: auto; }
</style>
