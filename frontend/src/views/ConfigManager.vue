<template>
  <div class="layout">
    <section class="panel summary">
      <h3>已发布版本</h3>
      <p class="version">{{ configs.published?.version || "暂无发布版本" }}</p>
      <p class="muted">发布时间：{{ configs.published?.publish_at || "未发布" }}</p>
      <p class="muted">{{ configs.published?.cdn_url || "等待发布" }}</p>
      <p v-if="configs.published?.cos_upload_status">
        同步状态：
        <span :class="syncClass(configs.published.cos_upload_status)">
          {{ syncLabel(configs.published.cos_upload_status) }}
        </span>
      </p>
    </section>

    <p v-if="errorMessage" class="feedback error">{{ errorMessage }}</p>
    <p v-if="successMessage" class="feedback success">{{ successMessage }}</p>

    <div class="content-grid">
      <section class="panel list-panel">
        <div class="panel-header">
          <h3>版本列表</h3>
          <button class="ghost" @click="createDraft">新建草稿</button>
        </div>
        <div class="list-group">
          <p v-if="allConfigs.length === 0" class="muted">当前还没有可编辑的配置版本。</p>
          <button
            v-for="item in allConfigs"
            :key="item.id"
            class="list-item"
            :class="{ active: selectedId === item.id }"
            @click="selectConfig(item.id)"
          >
            <strong>{{ item.version }}</strong>
            <span>{{ item.status }}</span>
            <span v-if="item.cos_upload_status" :class="['sync-badge', syncClass(item.cos_upload_status)]">
              {{ syncLabel(item.cos_upload_status) }}
            </span>
          </button>
        </div>
      </section>

      <section class="panel editor-panel">
        <div class="panel-header">
          <h3>JSON 编辑器</h3>
          <input v-model="changeLog" class="input" placeholder="变更说明" />
        </div>
        <textarea v-model="editorValue" class="editor" />
        <div class="actions">
          <button class="ghost" @click="saveDraft">保存草稿</button>
          <button class="primary" @click="publishCurrent">发布</button>
          <button v-if="selectedConfig?.status === 'archived'" class="ghost" @click="rollbackCurrent">
            回滚到此版本
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";

import {
  createConfig,
  getConfig,
  getConfigs,
  publishConfig,
  rollbackConfig,
  updateConfig,
} from "@/api/config";

type ConfigItem = Record<string, any>;

const configs = reactive<{ published: ConfigItem | null; drafts: ConfigItem[]; history: ConfigItem[] }>({
  published: null,
  drafts: [],
  history: [],
});
const selectedId = ref<number | null>(null);
const editorValue = ref("{\n  \"features\": {},\n  \"rules\": [],\n  \"urls\": {}\n}");
const changeLog = ref("");
const errorMessage = ref("");
const successMessage = ref("");

const allConfigs = computed(() => [configs.published, ...configs.drafts, ...configs.history].filter(Boolean) as ConfigItem[]);
const selectedConfig = computed(() => allConfigs.value.find((item) => item.id === selectedId.value) || null);

async function loadConfigs() {
  try {
    errorMessage.value = "";
    const response = await getConfigs();
    configs.published = response.data.published;
    configs.drafts = response.data.drafts;
    configs.history = response.data.history;
    if (!selectedId.value && allConfigs.value[0]) {
      await selectConfig(allConfigs.value[0].id);
    }
  } catch (error) {
    errorMessage.value = (error as Error).message;
  }
}

async function selectConfig(id: number) {
  try {
    errorMessage.value = "";
    selectedId.value = id;
    const response = await getConfig(id);
    editorValue.value = JSON.stringify(response.data.config_data || {}, null, 2);
    changeLog.value = response.data.change_log || "";
  } catch (error) {
    errorMessage.value = (error as Error).message;
  }
}

async function createDraft() {
  try {
    errorMessage.value = "";
    successMessage.value = "";
    const response = await createConfig({
      config_data: { features: {}, rules: [], urls: {} },
      change_log: "新建草稿",
    });
    successMessage.value = "草稿已创建";
    await loadConfigs();
    await selectConfig(response.data.id);
  } catch (error) {
    errorMessage.value = (error as Error).message;
  }
}

async function saveDraft() {
  if (!selectedId.value) return;
  try {
    errorMessage.value = "";
    successMessage.value = "";
    const payload = { config_data: JSON.parse(editorValue.value), change_log: changeLog.value };
    await updateConfig(selectedId.value, payload);
    successMessage.value = "草稿已保存";
    await loadConfigs();
  } catch (error) {
    errorMessage.value = error instanceof SyntaxError ? "配置 JSON 格式错误，请检查后重试" : (error as Error).message;
  }
}

async function publishCurrent() {
  if (!selectedId.value) return;
  try {
    errorMessage.value = "";
    successMessage.value = "";
    await publishConfig(selectedId.value);
    successMessage.value = "配置已发布";
    await loadConfigs();
  } catch (error) {
    errorMessage.value = (error as Error).message;
  }
}

async function rollbackCurrent() {
  if (!selectedId.value) return;
  try {
    errorMessage.value = "";
    successMessage.value = "";
    await rollbackConfig(selectedId.value);
    successMessage.value = "配置已回滚";
    await loadConfigs();
  } catch (error) {
    errorMessage.value = (error as Error).message;
  }
}

onMounted(loadConfigs);

function syncLabel(status: string): string {
  switch (status) {
    case "success": return "已同步";
    case "pending": return "同步中";
    case "failed": return "同步失败";
    default: return status;
  }
}

function syncClass(status: string): string {
  switch (status) {
    case "success": return "sync-success";
    case "pending": return "sync-pending";
    case "failed": return "sync-failed";
    default: return "";
  }
}
</script>

<style scoped>
.layout {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.content-grid {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 18px;
}

.panel {
  padding: 22px;
  border-radius: 24px;
  background: var(--panel-bg);
  border: 1px solid var(--border-soft);
  box-shadow: var(--panel-shadow);
}

.version {
  font-size: 28px;
  margin: 10px 0 6px;
}

.muted {
  color: var(--text-muted);
}

.feedback {
  margin: 0;
  padding: 12px 14px;
  border-radius: 14px;
}

.feedback.error {
  background: rgba(209, 89, 89, 0.18);
  color: #ffb0a8;
}

.feedback.success {
  background: rgba(83, 168, 123, 0.18);
  color: #8fe3b2;
}

.list-group {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.list-item,
.input,
.editor,
.ghost,
.primary {
  border-radius: 14px;
  border: 1px solid var(--border-soft);
}

.list-item {
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-primary);
  text-align: left;
  padding: 14px;
}

.list-item.active {
  border-color: rgba(214, 140, 69, 0.45);
}

.panel-header,
.actions {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.input,
.editor {
  width: 100%;
  background: rgba(8, 13, 13, 0.5);
  color: var(--text-primary);
  padding: 12px;
}

.editor {
  min-height: 420px;
  resize: vertical;
  margin: 14px 0;
  font-family: "Cascadia Code", Consolas, monospace;
}

.ghost,
.primary {
  padding: 10px 16px;
  color: var(--text-primary);
}

.ghost {
  background: rgba(255, 255, 255, 0.04);
}

.primary {
  background: linear-gradient(135deg, rgba(214, 140, 69, 0.92), rgba(182, 98, 43, 0.92));
}

.sync-badge {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
}

.sync-success {
  background: rgba(83, 168, 123, 0.2);
  color: #8fe3b2;
}

.sync-pending {
  background: rgba(214, 170, 69, 0.2);
  color: #f0d080;
}

.sync-failed {
  background: rgba(209, 89, 89, 0.2);
  color: #ffb0a8;
}

@media (max-width: 1000px) {
  .content-grid {
    grid-template-columns: 1fr;
  }
}
</style>
