<template>
  <div class="layout">
    <section class="panel toolbar">
      <label>包名 <input v-model.trim="packageFilter" class="input" placeholder="com.example.app" /></label>
      <button class="ghost" @click="loadConfigs({ resetPage: true })">筛选</button>
      <button class="primary" @click="createDraft">新建草稿</button>
    </section>
    <p v-if="feedback.error" data-testid="error-feedback" class="feedback error">{{ feedback.error }}</p>
    <p v-if="feedback.success" data-testid="success-feedback" class="feedback success">{{ feedback.success }}</p>
    <div class="content-grid">
      <section class="panel list-panel">
        <h3>配置版本</h3>
        <div ref="versionList" class="version-list" data-testid="version-list">
          <button v-for="item in visibleConfigs" :key="item.id" class="list-item" :class="{ active: selectedId === item.id }" @click="selectConfig(item.id)">
            <strong>{{ item.package_name }}</strong><span>{{ item.version }}</span><span>{{ item.status }}</span>
          </button>
        </div>
        <div class="version-pagination" aria-label="配置版本分页">
          <label for="version-page-size">每页条数</label>
          <select id="version-page-size" data-testid="version-page-size" :value="pageSize" @change="changePageSize">
            <option v-for="size in pageSizes" :key="size" :value="size">{{ size }}</option>
          </select>
          <button data-testid="version-prev" class="ghost" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
          <span data-testid="version-page">{{ page }} / {{ pageCount }}</span>
          <button data-testid="version-next" class="ghost" :disabled="page >= pageCount" @click="changePage(page + 1)">下一页</button>
          <span class="version-total">共 {{ allConfigs.length }} 条</span>
        </div>
      </section>
      <section class="panel editor-panel">
        <div class="panel-header">
          <div><h3>配置编辑器</h3><small>{{ selectedConfig?.package_name || "尚未选择配置" }}</small></div>
          <div class="mode"><button data-testid="json-mode" :class="{ primary: mode === 'json' }" @click="switchMode('json')">JSON</button><button data-testid="tree-mode" :class="{ primary: mode === 'tree' }" @click="switchMode('tree')">树形</button></div>
        </div>
        <input v-model="changeLog" class="input" placeholder="变更说明" />
        <textarea v-if="mode === 'json'" v-model="jsonText" data-testid="json-editor" class="editor" :disabled="!editable" />
        <template v-else>
          <ConfigFileTabs :model-value="activeFile" @update:model-value="selectActiveFile" />
          <ConfigTreeEditor :model-value="configData[activeFile]" :disabled="!editable" @update:model-value="updateActiveFile" @validation-change="treeValid = $event" />
        </template>
        <div class="actions">
          <button data-testid="save-config" class="ghost" :disabled="!editable || operationBusy" @click="saveDraft">{{ saving ? "正在加密保存…" : "保存草稿" }}</button>
          <button class="primary" :disabled="!editable || operationBusy" @click="publishCurrent">{{ publishing ? "正在发布…" : "发布" }}</button>
          <button v-if="selectedConfig?.status === 'archived'" class="ghost" @click="rollbackCurrent">回滚到此版本</button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";
import ConfigFileTabs, { type ConfigFileName } from "@/components/ConfigFileTabs.vue";
import ConfigTreeEditor from "@/components/ConfigTreeEditor.vue";
import { createConfig, getConfig, getConfigs, publishConfig, rollbackConfig, updateConfig } from "@/api/config";
import { validateConfigData, type JsonObject, type JsonValue } from "@/utils/configTree";
import { isPublishConfirmed, isRequestTimeout, isSaveConfirmed } from "@/utils/configOperation";
import { beginFeedback, setFeedbackError, setFeedbackSuccess } from "@/utils/feedback";

type ConfigItem = Record<string, any>;
const configs = reactive<{ published: ConfigItem[]; drafts: ConfigItem[]; history: ConfigItem[] }>({ published: [], drafts: [], history: [] });
const selectedId = ref<number | null>(null);
const packageFilter = ref("");
function emptyConfigData(): JsonObject { return { mainConfig: {}, newTouchConfig: {}, newTextRuleConfig: {} }; }
const configData = ref<JsonObject>(emptyConfigData());
const jsonText = ref(JSON.stringify(configData.value, null, 2));
const mode = ref<"tree" | "json">("tree");
const activeFile = ref<ConfigFileName>("mainConfig");
const treeValid = ref(true);
const changeLog = ref("");
const feedback = reactive({ error: "", success: "" });
const saving = ref(false);
const publishing = ref(false);
const pageSizes = [10, 20, 50];
const page = ref(1);
const pageSize = ref(10);
const versionList = ref<HTMLElement | null>(null);
let detailRequestSequence = 0;
const allConfigs = computed(() => [...configs.published, ...configs.drafts, ...configs.history]);
const pageCount = computed(() => Math.max(1, Math.ceil(allConfigs.value.length / pageSize.value)));
const visibleConfigs = computed(() => allConfigs.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value));
const selectedConfig = computed(() => allConfigs.value.find((item) => item.id === selectedId.value) || null);
const editable = computed(() => selectedConfig.value?.status === "draft");
const operationBusy = computed(() => saving.value || publishing.value);

function message(error: unknown) { return error instanceof SyntaxError ? "配置 JSON 格式错误" : (error as Error).message; }
function clampPage() { page.value = Math.min(page.value, pageCount.value); }
function scrollVersionListToTop() { void nextTick(() => { if (versionList.value) versionList.value.scrollTop = 0; }); }
function changePage(nextPage: number) {
  const next = Math.max(1, Math.min(nextPage, pageCount.value));
  if (next === page.value) return;
  page.value = next;
  scrollVersionListToTop();
}
function changePageSize(event: Event) {
  const value = Number((event.target as HTMLSelectElement).value);
  if (!pageSizes.includes(value)) return;
  pageSize.value = value;
  page.value = 1;
  scrollVersionListToTop();
}
function parseJsonData(): JsonObject {
  const value: unknown = JSON.parse(jsonText.value);
  validateConfigData(value);
  return value;
}
function currentData(): JsonObject {
  if (mode.value === "json") configData.value = parseJsonData();
  validateConfigData(configData.value);
  return configData.value;
}
function updateActiveFile(value: JsonValue) {
  configData.value = { ...configData.value, [activeFile.value]: value };
}
function requireValidTree(): boolean {
  if (mode.value === "tree" && !treeValid.value) {
    setFeedbackError(feedback, "请先修正当前配置文件中的树形配置错误");
    return false;
  }
  return true;
}
function selectActiveFile(next: ConfigFileName): void {
  if (next === activeFile.value || !requireValidTree()) return;
  activeFile.value = next;
  treeValid.value = true;
  beginFeedback(feedback);
}
async function switchMode(next: "tree" | "json") {
  try {
    if (next === mode.value) return;
    if (next === "json" && !requireValidTree()) return;
    if (next === "tree") configData.value = parseJsonData();
    else {
      validateConfigData(configData.value);
      jsonText.value = JSON.stringify(configData.value, null, 2);
    }
    mode.value = next; beginFeedback(feedback);
  } catch (error) { setFeedbackError(feedback, message(error)); }
}
async function loadConfigs(options: { resetPage?: boolean } = {}) {
  try {
    beginFeedback(feedback);
    if (options.resetPage) page.value = 1;
    const response = await getConfigs(packageFilter.value);
    configs.published = Array.isArray(response.data.published) ? response.data.published : response.data.published ? [response.data.published] : [];
    configs.drafts = response.data.drafts; configs.history = response.data.history;
    clampPage();
    if (!allConfigs.value.some((item) => item.id === selectedId.value)) selectedId.value = null;
    if (!selectedId.value && allConfigs.value[0]) await selectConfig(allConfigs.value[0].id);
  } catch (error) { setFeedbackError(feedback, message(error)); }
}
async function selectConfig(id: number) {
  const requestSequence = ++detailRequestSequence;
  try {
    beginFeedback(feedback);
    const response = await getConfig(id);
    validateConfigData(response.data.config_data);
    if (requestSequence !== detailRequestSequence) return;
    selectedId.value = id;
    configData.value = response.data.config_data;
    jsonText.value = JSON.stringify(configData.value, null, 2);
    activeFile.value = "mainConfig";
    treeValid.value = true;
    changeLog.value = response.data.change_log || "";
  }
  catch (error) {
    if (requestSequence === detailRequestSequence) setFeedbackError(feedback, message(error));
  }
}
async function createDraft() {
  try {
    beginFeedback(feedback);
    if (!packageFilter.value) throw new Error("请先输入包名");
    const response = await createConfig({ package_name: packageFilter.value, config_data: { mainConfig: {}, newTouchConfig: {}, newTextRuleConfig: {} }, change_log: "新建草稿" });
    await loadConfigs();
    const draftIndex = allConfigs.value.findIndex((item) => item.id === response.data.id);
    if (draftIndex >= 0) {
      page.value = Math.floor(draftIndex / pageSize.value) + 1;
      scrollVersionListToTop();
    }
    await selectConfig(response.data.id); setFeedbackSuccess(feedback, "草稿已加密保存");
  } catch (error) { setFeedbackError(feedback, message(error)); }
}
async function saveDraft() {
  if (!selectedId.value || !editable.value) return;
  if (!requireValidTree()) return;
  const configId = selectedId.value;
  const before = { ...selectedConfig.value };
  try {
    beginFeedback(feedback);
    const data = currentData();
    saving.value = true;
    await updateConfig(configId, { config_data: data, change_log: changeLog.value });
    await loadConfigs(); setFeedbackSuccess(feedback, "配置已加密保存");
  } catch (error) {
    if (isRequestTimeout(error)) {
      try {
        const response = await getConfig(configId);
        if (isSaveConfirmed(before, response.data)) {
          await loadConfigs(); setFeedbackSuccess(feedback, "请求虽超时，但已确认配置保存成功"); return;
        }
      } catch { /* 保留原始超时错误 */ }
    }
    setFeedbackError(feedback, message(error));
  } finally { saving.value = false; }
}
async function publishCurrent() {
  if (!selectedId.value || !editable.value) return;
  if (!requireValidTree()) return;
  const configId = selectedId.value;
  const before = { ...selectedConfig.value };
  try {
    beginFeedback(feedback);
    currentData();
    publishing.value = true;
    await publishConfig(configId); await loadConfigs(); setFeedbackSuccess(feedback, "配置已发布");
  } catch (error) {
    if (isRequestTimeout(error)) {
      try {
        const response = await getConfig(configId);
        if (isPublishConfirmed(before, response.data)) {
          await loadConfigs(); setFeedbackSuccess(feedback, "请求虽超时，但已确认配置发布成功"); return;
        }
      } catch { /* 保留原始超时错误 */ }
    }
    setFeedbackError(feedback, message(error));
  } finally { publishing.value = false; }
}
async function rollbackCurrent() { if (selectedId.value) { try { beginFeedback(feedback); await rollbackConfig(selectedId.value); await loadConfigs(); setFeedbackSuccess(feedback, "配置已回滚为新版本"); } catch (error) { setFeedbackError(feedback, message(error)); } } }
watch(() => allConfigs.value.length, clampPage);
onMounted(loadConfigs);
</script>

<style scoped>
.layout { display:flex; flex-direction:column; gap:20px; }.content-grid{display:grid;grid-template-columns:340px 1fr;gap:18px;align-items:start}.panel{padding:22px;border-radius:24px;background:var(--panel-bg);border:1px solid var(--border-soft);box-shadow:var(--panel-shadow)}.toolbar,.panel-header,.actions,.mode{display:flex;gap:12px;align-items:center}.toolbar label{display:flex;gap:10px;align-items:center;flex:1}.input,.editor,button{border-radius:12px;border:1px solid var(--border-soft);background:rgba(8,13,13,.5);color:var(--text-primary);padding:10px}.input{width:100%}.editor{width:100%;min-height:min(420px,45vh);margin:14px 0;font-family:"Cascadia Code",Consolas,monospace}.list-panel{display:flex;flex-direction:column;max-height:min(720px,calc(100vh - 220px));overflow:hidden}.list-panel h3,.version-pagination{flex-shrink:0}.version-list{flex:1 1 auto;min-height:0;overflow-y:auto;overscroll-behavior:contain}.list-item{display:flex;flex-direction:column;width:100%;margin-top:10px;text-align:left}.list-item.active{border-color:#d68c45}.version-pagination{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:14px}.version-pagination select{border-radius:10px;border:1px solid var(--border-soft);background:rgba(8,13,13,.5);color:var(--text-primary);padding:8px}.version-total{margin-left:auto;color:var(--text-muted)}.primary{background:#b6622b}.feedback{padding:12px;border-radius:12px}.error{color:#ffb0a8}.success{color:#8fe3b2}@media(max-width:1000px){.content-grid{grid-template-columns:1fr}.list-panel{max-height:min(55vh,520px)}}
.layout,.panel,.content-grid,.content-grid > *, .editor-panel,.list-panel { min-width: 0; }
.layout,.content-grid,.editor-panel,.list-panel { min-height: 0; }
.editor { max-width: 100%; min-width: 0; overflow: auto; }
</style>
