<template>
  <div class="stack">
    <section class="panel">
      <div class="panel-header">
        <div class="tabs">
          <button :class="{ active: platform === 'ios' }" @click="switchPlatform('ios')">iOS</button>
          <button :class="{ active: platform === 'android' }" @click="switchPlatform('android')">Android</button>
        </div>
        <button class="primary" @click="openCreate">新增版本</button>
      </div>
    </section>

    <section class="panel">
      <table class="table">
        <thead>
          <tr>
            <th>版本号</th>
            <th>版本名</th>
            <th>更新策略</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="versions.length === 0">
            <td colspan="5" class="empty-state">当前平台还没有版本记录。</td>
          </tr>
          <tr v-for="item in versions" :key="item.id">
            <td>{{ item.version_code }}</td>
            <td>{{ item.version_name }}</td>
            <td>{{ item.update_policy }}</td>
            <td>{{ item.status }}</td>
            <td class="actions-inline">
              <button class="ghost" @click="editVersion(item)">编辑</button>
              <button class="ghost" @click="toggleStatus(item)">
                {{ item.status === "active" ? "停用" : "启用" }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <p v-if="errorMessage" class="feedback error">{{ errorMessage }}</p>

    <div v-if="dialogVisible" class="dialog-backdrop" @click.self="closeDialog">
      <section class="dialog">
        <div class="panel-header">
          <h3>{{ editingId ? "编辑版本" : "新增版本" }}</h3>
          <button class="ghost" @click="closeDialog">关闭</button>
        </div>
        <div class="form-grid">
          <input v-model="form.version_name" class="input" placeholder="版本名" />
          <input v-model.number="form.version_code" class="input" type="number" placeholder="版本号" />
          <select v-model="form.update_policy" class="input">
            <option value="force">force</option>
            <option value="suggest">suggest</option>
            <option value="silent">silent</option>
          </select>
          <select v-model="form.status" class="input">
            <option value="active">active</option>
            <option value="inactive">inactive</option>
          </select>
          <input v-model="form.download_url" class="input span-2" placeholder="下载地址" />
          <input v-model.number="form.file_size" class="input" type="number" placeholder="文件大小" />
          <input v-model="form.file_hash" class="input" placeholder="文件 Hash" />
          <textarea v-model="form.release_notes" class="input span-2 notes" placeholder="发布说明" />
        </div>
        <div class="actions">
          <button class="primary" @click="submitForm">{{ editingId ? "保存修改" : "创建版本" }}</button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";

import { createVersion, getVersions, updateVersion } from "@/api/version";

const platform = ref<"ios" | "android">("ios");
const versions = ref<Array<Record<string, any>>>([]);
const editingId = ref<number | null>(null);
const dialogVisible = ref(false);
const errorMessage = ref("");
const form = reactive({
  platform: "ios",
  version_code: 100,
  version_name: "1.0.0",
  update_policy: "suggest",
  download_url: "",
  release_notes: "",
  file_size: undefined as number | undefined,
  file_hash: "",
  status: "active",
});

async function loadVersions() {
  try {
    errorMessage.value = "";
    const response = await getVersions({ platform: platform.value });
    versions.value = response.data;
  } catch (error) {
    errorMessage.value = (error as Error).message;
  }
}

function switchPlatform(value: "ios" | "android") {
  platform.value = value;
  form.platform = value;
  editingId.value = null;
  dialogVisible.value = false;
  void loadVersions();
}

function openCreate() {
  editingId.value = null;
  dialogVisible.value = true;
  form.platform = platform.value;
  form.version_code = 100;
  form.version_name = "1.0.0";
  form.update_policy = "suggest";
  form.download_url = "";
  form.release_notes = "";
  form.file_size = undefined;
  form.file_hash = "";
  form.status = "active";
}

function editVersion(item: Record<string, any>) {
  editingId.value = item.id;
  dialogVisible.value = true;
  Object.assign(form, item);
}

function closeDialog() {
  dialogVisible.value = false;
}

async function toggleStatus(item: Record<string, any>) {
  try {
    errorMessage.value = "";
    await updateVersion(item.id, {
      status: item.status === "active" ? "inactive" : "active",
    });
    await loadVersions();
  } catch (error) {
    errorMessage.value = (error as Error).message;
  }
}

async function submitForm() {
  try {
    errorMessage.value = "";
    if (editingId.value) {
      await updateVersion(editingId.value, { ...form });
    } else {
      await createVersion({ ...form, platform: platform.value });
    }
    closeDialog();
    await loadVersions();
  } catch (error) {
    errorMessage.value = (error as Error).message;
  }
}

onMounted(loadVersions);
</script>

<style scoped>
.stack {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.panel {
  padding: 22px;
  border-radius: 24px;
  background: var(--panel-bg);
  border: 1px solid var(--border-soft);
  box-shadow: var(--panel-shadow);
}

.panel-header,
.tabs,
.actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.panel-header {
  justify-content: space-between;
}

.actions-inline {
  display: flex;
  gap: 8px;
}

.tabs button,
.ghost,
.primary,
.input {
  border-radius: 12px;
  border: 1px solid var(--border-soft);
  color: var(--text-primary);
}

.tabs button,
.ghost,
.primary {
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.04);
}

.tabs button.active {
  background: rgba(214, 140, 69, 0.22);
}

.primary {
  background: linear-gradient(135deg, rgba(214, 140, 69, 0.92), rgba(182, 98, 43, 0.92));
}

.table {
  width: 100%;
  border-collapse: collapse;
}

.table th,
.table td {
  padding: 12px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.input {
  background: rgba(8, 13, 13, 0.5);
  padding: 12px;
}

.span-2 {
  grid-column: span 2;
}

.notes {
  min-height: 120px;
}

.dialog-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(4, 10, 12, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.dialog {
  width: min(780px, 100%);
  padding: 22px;
  border-radius: 24px;
  background: var(--panel-bg);
  border: 1px solid var(--border-soft);
  box-shadow: var(--panel-shadow);
}

.feedback.error {
  margin: 0;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(209, 89, 89, 0.18);
  color: #ffb0a8;
}

.empty-state {
  text-align: center;
  color: var(--text-muted);
}

@media (max-width: 800px) {
  .form-grid {
    grid-template-columns: 1fr;
  }

  .span-2 {
    grid-column: span 1;
  }
}
</style>
