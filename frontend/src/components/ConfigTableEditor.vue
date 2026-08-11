<template>
  <div class="table-editor">
    <table>
      <thead><tr><th>字段路径</th><th>类型</th><th>字段值</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="(row, index) in modelValue" :key="index">
          <td><input v-model="row.path" :disabled="disabled" /></td>
          <td><select v-model="row.type" :disabled="disabled"><option v-for="type in types" :key="type">{{ type }}</option></select></td>
          <td><input v-model="row.value" :disabled="disabled || row.type === 'null'" /></td>
          <td><button type="button" :disabled="disabled" @click="remove(index)">删除</button></td>
        </tr>
      </tbody>
    </table>
    <button type="button" :disabled="disabled" @click="add">新增字段</button>
  </div>
</template>

<script setup lang="ts">
import type { ConfigRow, ValueType } from "@/utils/configTable";
const props = defineProps<{ modelValue: ConfigRow[]; disabled?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [rows: ConfigRow[]] }>();
const types: ValueType[] = ["string", "number", "boolean", "null", "object", "array"];
function add() { emit("update:modelValue", [...props.modelValue, { path: "", type: "string", value: "" }]); }
function remove(index: number) { emit("update:modelValue", props.modelValue.filter((_, i) => i !== index)); }
</script>

<style scoped>
table { width: 100%; border-collapse: collapse; margin: 14px 0; }
th, td { padding: 8px; border-bottom: 1px solid var(--border-soft); text-align: left; }
input, select, button { width: 100%; padding: 8px; color: var(--text-primary); background: rgba(8,13,13,.5); border: 1px solid var(--border-soft); border-radius: 8px; }
</style>
