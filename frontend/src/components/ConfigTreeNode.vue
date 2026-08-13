<template>
  <div class="tree-node" data-testid="tree-node" :data-path="JSON.stringify(path)">
    <div class="node-row">
      <button
        v-if="isContainer"
        data-testid="collapse-toggle"
        class="icon-button"
        type="button"
        :aria-label="collapsed ? '展开节点' : '折叠节点'"
        @click="collapsed = !collapsed"
      >
        {{ collapsed ? "▶" : "▼" }}
      </button>
      <span v-else class="toggle-placeholder" />

      <template v-if="parentKind === 'object'">
        <input v-model="renameKey" data-testid="rename-input" class="key-input" :disabled="disabled" />
        <button
          data-testid="rename-button"
          data-mutation-control="true"
          type="button"
          :disabled="disabled || renameKey === nodeKey"
          @click="emit('rename', { path, key: renameKey })"
        >改名</button>
      </template>
      <span v-else class="node-key">{{ displayKey }}</span>

      <select
        data-testid="type-select"
        data-mutation-control="true"
        :value="nodeType"
        :disabled="disabled"
        @change="replaceType"
      >
        <option v-for="type in jsonTypes" :key="type" :value="type">{{ type }}</option>
      </select>

      <input
        v-if="nodeType === 'string'"
        data-testid="string-input"
        :value="value"
        :disabled="disabled"
        @input="emit('replace', { path, value: ($event.target as HTMLInputElement).value })"
      />
      <input
        v-else-if="nodeType === 'number'"
        data-testid="number-input"
        type="text"
        :value="numberText"
        :disabled="disabled"
        @input="replaceNumber"
      />
      <select
        v-else-if="nodeType === 'boolean'"
        data-testid="boolean-input"
        :value="String(value)"
        :disabled="disabled"
        @change="emit('replace', { path, value: ($event.target as HTMLSelectElement).value === 'true' })"
      >
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
      <span v-else-if="nodeType === 'null'" data-testid="null-value" class="node-value">null</span>
      <span v-else class="node-value">{{ children.length }} 项</span>

      <button data-testid="copy-node" type="button" @click="copyNode">复制</button>
      <button
        v-if="parentKind === 'array'"
        data-testid="duplicate-node"
        data-mutation-control="true"
        type="button"
        :disabled="disabled"
        @click="emit('duplicate', { path })"
      >复制项</button>
      <button
        v-if="parentKind === 'array'"
        data-testid="move-up"
        data-mutation-control="true"
        type="button"
        :disabled="disabled || nodeKey === 0"
        @click="emit('move', { path, direction: -1 })"
      >上移</button>
      <button
        v-if="parentKind === 'array'"
        data-testid="move-down"
        data-mutation-control="true"
        type="button"
        :disabled="disabled || nodeKey === siblingCount - 1"
        @click="emit('move', { path, direction: 1 })"
      >下移</button>
      <button
        v-if="parentKind !== 'root'"
        data-testid="remove-node"
        data-mutation-control="true"
        type="button"
        :disabled="disabled"
        @click="emit('remove', { path })"
      >删除</button>
    </div>

    <p v-if="numberError || nodeError" data-testid="node-error" class="node-error">
      {{ numberError || nodeError }}
    </p>

    <div v-if="isContainer && !collapsed" data-testid="container-children" class="container-children">
      <div class="add-row">
        <input
          v-if="nodeType === 'object'"
          v-model="childKey"
          data-testid="add-key"
          :disabled="disabled"
          placeholder="字段名"
        />
        <select v-model="childType" data-testid="add-type" :disabled="disabled">
          <option v-for="type in jsonTypes" :key="type" :value="type">{{ type }}</option>
        </select>
        <button
          data-testid="add-child"
          data-mutation-control="true"
          type="button"
          :disabled="disabled"
          @click="addChild"
        >新增子项</button>
      </div>

      <ConfigTreeNode
        v-for="child in children"
        :key="child.identity.id"
        :node-key="child.key"
        :value="child.value"
        :identity="child.identity"
        :path="[...path, child.key]"
        :parent-kind="containerKind"
        :disabled="disabled"
        :sibling-count="children.length"
        :node-error="errorForPath([...path, child.key])"
        :error-for-path="errorForPath"
        @add-child="emit('add-child', $event)"
        @add-sibling="emit('add-sibling', $event)"
        @rename="emit('rename', $event)"
        @replace="emit('replace', $event)"
        @remove="emit('remove', $event)"
        @duplicate="emit('duplicate', $event)"
        @move="emit('move', $event)"
      />
    </div>

    <div v-if="parentKind === 'object'" class="sibling-row">
      <input v-model="siblingKey" data-testid="sibling-key" :disabled="disabled" placeholder="同级字段名" />
      <select v-model="siblingType" data-testid="sibling-type" :disabled="disabled">
        <option v-for="type in jsonTypes" :key="type" :value="type">{{ type }}</option>
      </select>
      <button
        data-testid="add-sibling"
        data-mutation-control="true"
        type="button"
        :disabled="disabled"
        @click="emit('add-sibling', { path, key: siblingKey, value: defaultValueForType(siblingType) })"
      >新增同级</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";

import {
  defaultValueForType,
  jsonTypeOf,
  type JsonType,
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

const props = withDefaults(defineProps<{
  nodeKey: string | number;
  value: JsonValue;
  identity: NodeIdentity;
  path: TreePath;
  parentKind: "root" | "object" | "array";
  disabled?: boolean;
  siblingCount?: number;
  nodeError?: string;
  errorForPath?: (path: TreePath) => string;
}>(), {
  disabled: false,
  siblingCount: 1,
  nodeError: "",
  errorForPath: () => "",
});

const emit = defineEmits<{
  "add-child": [payload: AddPayload];
  "add-sibling": [payload: AddPayload];
  rename: [payload: RenamePayload];
  replace: [payload: ReplacePayload];
  remove: [payload: PathPayload];
  duplicate: [payload: PathPayload];
  move: [payload: MovePayload];
}>();

const jsonTypes: JsonType[] = ["string", "number", "boolean", "null", "object", "array"];
const collapsed = ref(false);
const renameKey = ref(String(props.nodeKey));
const childKey = ref("");
const childType = ref<JsonType>("string");
const siblingKey = ref("");
const siblingType = ref<JsonType>("string");
const numberText = ref(typeof props.value === "number" ? String(props.value) : "");
const numberError = ref("");

watch(() => props.nodeKey, (key) => { renameKey.value = String(key); });
watch(() => props.value, (value) => {
  if (typeof value === "number") numberText.value = String(value);
});

const nodeType = computed(() => jsonTypeOf(props.value));
const isContainer = computed(() => nodeType.value === "object" || nodeType.value === "array");
const containerKind = computed<"object" | "array">(() => Array.isArray(props.value) ? "array" : "object");
const displayKey = computed(() => props.parentKind === "root" ? "根节点" : `[${props.nodeKey}]`);
const children = computed(() => {
  if (Array.isArray(props.value)) {
    const identities = props.identity.children as NodeIdentity[];
    return props.value.map((value, key) => ({ key, value, identity: identities[key] }));
  }
  if (props.value !== null && typeof props.value === "object") {
    const identities = props.identity.children as Record<string, NodeIdentity>;
    return Object.entries(props.value).map(([key, value]) => ({ key, value, identity: identities[key] }));
  }
  return [];
});

function replaceType(event: Event): void {
  const select = event.target as HTMLSelectElement;
  const type = select.value as JsonType;
  if (type !== nodeType.value) emit("replace", { path: props.path, value: defaultValueForType(type) });
  select.value = nodeType.value;
}

function replaceNumber(event: Event): void {
  numberText.value = (event.target as HTMLInputElement).value;
  const parsed = Number(numberText.value);
  if (numberText.value.trim() === "" || !Number.isFinite(parsed)) {
    numberError.value = "数值必须是有限数字";
    return;
  }
  numberError.value = "";
  emit("replace", { path: props.path, value: parsed });
}

function addChild(): void {
  emit("add-child", {
    path: props.path,
    key: nodeType.value === "object" ? childKey.value : undefined,
    value: defaultValueForType(childType.value),
  });
}

async function copyNode(): Promise<void> {
  const text = typeof props.value === "string" ? props.value : JSON.stringify(props.value, null, 2);
  await navigator.clipboard.writeText(text);
}
</script>

<style scoped>
.tree-node { margin: 8px 0; }
.node-row, .add-row, .sibling-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.node-row input, .node-row select, .add-row input, .add-row select, .sibling-row input, .sibling-row select,
.tree-node button { padding: 7px 9px; border: 1px solid var(--border-soft); border-radius: 8px; color: var(--text-primary); background: rgba(8, 13, 13, 0.5); }
.key-input { width: 150px; }
.node-key { min-width: 80px; font-weight: 600; }
.node-value { color: var(--text-muted); }
.icon-button { min-width: 32px; }
.toggle-placeholder { width: 32px; }
.container-children { margin-left: 22px; padding-left: 14px; border-left: 1px solid var(--border-soft); }
.add-row { margin: 8px 0 12px; }
.sibling-row { margin: 6px 0 6px 54px; }
.node-error { margin: 6px 0 6px 54px; color: #ffb0a8; }
button:disabled, input:disabled, select:disabled { cursor: not-allowed; opacity: 0.5; }
</style>
