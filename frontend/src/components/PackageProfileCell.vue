<template>
  <div class="profile-cell">
    <template v-if="!editing">
      <span data-testid="profile-value" class="profile-value" @click="startEdit">{{ committedValue }}</span>
      <button data-testid="profile-edit" type="button" :disabled="disabled" @click="startEdit">编辑</button>
    </template>
    <template v-else>
      <input
        ref="input"
        data-testid="profile-input"
        :aria-label="fieldLabel"
        type="text"
        :value="draftValue"
        :disabled="disabled || saving"
        @input="updateDraft"
      />
      <span class="edit-actions">
        <button data-testid="profile-save" type="button" :disabled="disabled || saving" @click="save">保存</button>
        <button data-testid="profile-cancel" type="button" :disabled="saving" @click="cancel">取消</button>
      </span>
    </template>
    <span v-if="errorMessage" data-testid="profile-error" class="profile-error" role="alert">{{ errorMessage }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";

import type { PackageProfile, PackageProfilePayload } from "@/api/logAnalysis";
import { putPackageProfile } from "@/api/logAnalysis";

export type PackageProfileField = "alias" | "company" | "account";

const props = withDefaults(
  defineProps<{
    packageName: string;
    field: PackageProfileField;
    modelValue?: string | null;
    value?: string | null;
    profile?: Partial<PackageProfile>;
    disabled?: boolean;
  }>(),
  { modelValue: undefined, value: undefined, profile: undefined, disabled: false },
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
  saved: [payload: { field: PackageProfileField; value: string; profile: Partial<PackageProfile> }];
  "save-error": [message: string];
}>();

const input = ref<HTMLInputElement | null>(null);
const editing = ref(false);
const saving = ref(false);
const draftValue = ref("");
const errorMessage = ref("");
const requestSequence = ref(0);

const committedValue = computed(() => {
  const directValue = props.modelValue ?? props.value;
  if (directValue !== undefined && directValue !== null) return directValue;
  const profileValue = props.profile?.[props.field];
  return typeof profileValue === "string" ? profileValue : "";
});
const fieldLabel = computed(() => ({ alias: "别名", company: "公司", account: "账户" })[props.field]);

watch([() => props.packageName, () => props.field], () => {
  requestSequence.value += 1;
  saving.value = false;
  editing.value = false;
  errorMessage.value = "";
  draftValue.value = committedValue.value;
});

watch(committedValue, (value) => {
  if (!editing.value && !saving.value) draftValue.value = value;
}, { immediate: true });

function startEdit() {
  if (props.disabled) return;
  draftValue.value = committedValue.value;
  errorMessage.value = "";
  editing.value = true;
  void nextTick(() => input.value?.focus());
}

function updateDraft(event: Event) {
  draftValue.value = (event.target as HTMLInputElement).value;
}

function cancel() {
  if (saving.value) return;
  editing.value = false;
  errorMessage.value = "";
  draftValue.value = committedValue.value;
}

function responseProfile(response: unknown): Partial<PackageProfile> {
  if (!response || typeof response !== "object") return {};
  const outer = response as { data?: unknown };
  const body = outer.data && typeof outer.data === "object" ? outer.data : response;
  if (!body || typeof body !== "object") return {};
  const nested = body as { data?: unknown };
  return nested.data && typeof nested.data === "object" ? nested.data as Partial<PackageProfile> : body as Partial<PackageProfile>;
}

function errorText(error: unknown) {
  return error instanceof Error && error.message ? error.message : "保存失败";
}

async function save() {
  if (props.disabled || saving.value) return;
  const sequence = ++requestSequence.value;
  const value = draftValue.value;
  saving.value = true;
  errorMessage.value = "";
  const payload: PackageProfilePayload = { [props.field]: value };
  try {
    const response = await putPackageProfile(props.packageName, payload);
    if (sequence !== requestSequence.value) return;
    const profile = responseProfile(response);
    const savedValue = typeof profile[props.field] === "string" ? profile[props.field] as string : value;
    emit("update:modelValue", savedValue);
    emit("saved", { field: props.field, value: savedValue, profile });
    editing.value = false;
    draftValue.value = savedValue;
  } catch (error) {
    if (sequence !== requestSequence.value) return;
    errorMessage.value = errorText(error);
    emit("save-error", errorMessage.value);
  } finally {
    if (sequence === requestSequence.value) saving.value = false;
  }
}
</script>

<style scoped>
.profile-cell { display: inline-flex; align-items: center; flex-wrap: wrap; gap: 6px; min-width: 90px; }
.profile-value { min-width: 24px; min-height: 20px; cursor: text; }
input { min-width: 110px; box-sizing: border-box; border: 1px solid var(--border-soft); border-radius: 6px; background: rgba(8, 13, 13, .5); color: var(--text-primary); padding: 5px 7px; }
button { border: 1px solid var(--border-soft); border-radius: 6px; background: rgba(8, 13, 13, .5); color: var(--text-primary); padding: 5px 7px; cursor: pointer; }
button:disabled, input:disabled { cursor: not-allowed; opacity: .55; }
.edit-actions { display: inline-flex; gap: 4px; }
.profile-error { flex-basis: 100%; color: #ef8f82; font-size: 12px; }
</style>
