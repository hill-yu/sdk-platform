<template>
  <div class="layout">
    <section class="panel toolbar">
      <label>包名 <input v-model.trim="packageFilter" class="input" placeholder="com.example.app" /></label>
      <button class="ghost" @click="loadConfigs">筛选</button>
      <button class="primary" @click="createDraft">新建草稿</button>
    </section>
    <p v-if="errorMessage" class="feedback error">{{ errorMessage }}</p>
    <p v-if="successMessage" class="feedback success">{{ successMessage }}</p>
    <div class="content-grid">
      <section class="panel list-panel">
        <h3>配置版本</h3>
        <button v-for="item in allConfigs" :key="item.id" class="list-item" :class="{ active: selectedId === item.id }" @click="selectConfig(item.id)">
          <strong>{{ item.package_name }}</strong><span>{{ item.version }}</span><span>{{ item.status }}</span>
        </button>
      </section>
      <section class="panel editor-panel">
        <div class="panel-header">
          <div><h3>配置编辑器</h3><small>{{ selectedConfig?.package_name || "尚未选择配置" }}</small></div>
          <div class="mode"><button :class="{ primary: mode === 'json' }" @click="switchMode('json')">JSON</button><button :class="{ primary: mode === 'table' }" @click="switchMode('table')">表格</button></div>
        </div>
        <input v-model="changeLog" class="input" placeholder="变更说明" />
        <textarea v-if="mode === 'json'" v-model="editorValue" class="editor" :disabled="!editable" />
        <ConfigTableEditor v-else v-model="tableRows" :disabled="!editable" />
        <div class="actions">
          <button class="ghost" :disabled="!editable" @click="saveDraft">保存草稿</button>
          <button class="primary" :disabled="!editable" @click="publishCurrent">发布</button>
          <button v-if="selectedConfig?.status === 'archived'" class="ghost" @click="rollbackCurrent">回滚到此版本</button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import ConfigTableEditor from "@/components/ConfigTableEditor.vue";
import { createConfig, getConfig, getConfigs, publishConfig, rollbackConfig, updateConfig } from "@/api/config";
import { flattenConfig, rowsToConfig, type ConfigRow } from "@/utils/configTable";

type ConfigItem = Record<string, any>;
const configs = reactive<{ published: ConfigItem[]; drafts: ConfigItem[]; history: ConfigItem[] }>({ published: [], drafts: [], history: [] });
const selectedId = ref<number | null>(null);
const packageFilter = ref("");
const editorValue = ref("{\n  \"mainConfig\": {},\n  \"newTouchConfig\": {},\n  \"newTextRuleConfig\": {}\n}");
const tableRows = ref<ConfigRow[]>([]);
const mode = ref<"json" | "table">("json");
const changeLog = ref("");
const errorMessage = ref("");
const successMessage = ref("");
const allConfigs = computed(() => [...configs.published, ...configs.drafts, ...configs.history]);
const selectedConfig = computed(() => allConfigs.value.find((item) => item.id === selectedId.value) || null);
const editable = computed(() => selectedConfig.value?.status === "draft");

function message(error: unknown) { return error instanceof SyntaxError ? "配置 JSON 格式错误" : (error as Error).message; }
function currentData() { return mode.value === "json" ? JSON.parse(editorValue.value) : rowsToConfig(tableRows.value); }
async function switchMode(next: "json" | "table") {
  try {
    if (next === mode.value) return;
    if (next === "table") tableRows.value = flattenConfig(JSON.parse(editorValue.value));
    else editorValue.value = JSON.stringify(rowsToConfig(tableRows.value), null, 2);
    mode.value = next; errorMessage.value = "";
  } catch (error) { errorMessage.value = message(error); }
}
async function loadConfigs() {
  try {
    const response = await getConfigs(packageFilter.value);
    configs.published = Array.isArray(response.data.published) ? response.data.published : response.data.published ? [response.data.published] : [];
    configs.drafts = response.data.drafts; configs.history = response.data.history;
    if (!allConfigs.value.some((item) => item.id === selectedId.value)) selectedId.value = null;
    if (!selectedId.value && allConfigs.value[0]) await selectConfig(allConfigs.value[0].id);
  } catch (error) { errorMessage.value = message(error); }
}
async function selectConfig(id: number) {
  try { const response = await getConfig(id); selectedId.value = id; editorValue.value = JSON.stringify(response.data.config_data, null, 2); tableRows.value = flattenConfig(response.data.config_data); changeLog.value = response.data.change_log || ""; }
  catch (error) { errorMessage.value = message(error); }
}
async function createDraft() {
  try {
    if (!packageFilter.value) throw new Error("请先输入包名");
    const response = await createConfig({ package_name: packageFilter.value, config_data: { mainConfig: {}, newTouchConfig: {}, newTextRuleConfig: {} }, change_log: "新建草稿" });
    successMessage.value = "草稿已加密保存"; await loadConfigs(); await selectConfig(response.data.id);
  } catch (error) { errorMessage.value = message(error); }
}
async function saveDraft() {
  if (!selectedId.value || !editable.value) return;
  try { await updateConfig(selectedId.value, { config_data: currentData(), change_log: changeLog.value }); successMessage.value = "配置已加密保存"; await loadConfigs(); }
  catch (error) { errorMessage.value = message(error); }
}
async function publishCurrent() { if (selectedId.value && editable.value) { try { await publishConfig(selectedId.value); successMessage.value = "配置已发布"; await loadConfigs(); } catch (error) { errorMessage.value = message(error); } } }
async function rollbackCurrent() { if (selectedId.value) { try { await rollbackConfig(selectedId.value); successMessage.value = "配置已回滚为新版本"; await loadConfigs(); } catch (error) { errorMessage.value = message(error); } } }
onMounted(loadConfigs);
</script>

<style scoped>
.layout { display:flex; flex-direction:column; gap:20px; }.content-grid{display:grid;grid-template-columns:340px 1fr;gap:18px}.panel{padding:22px;border-radius:24px;background:var(--panel-bg);border:1px solid var(--border-soft);box-shadow:var(--panel-shadow)}.toolbar,.panel-header,.actions,.mode{display:flex;gap:12px;align-items:center}.toolbar label{display:flex;gap:10px;align-items:center;flex:1}.input,.editor,button{border-radius:12px;border:1px solid var(--border-soft);background:rgba(8,13,13,.5);color:var(--text-primary);padding:10px}.input{width:100%}.editor{width:100%;min-height:420px;margin:14px 0;font-family:"Cascadia Code",Consolas,monospace}.list-item{display:flex;flex-direction:column;width:100%;margin-top:10px;text-align:left}.list-item.active{border-color:#d68c45}.primary{background:#b6622b}.feedback{padding:12px;border-radius:12px}.error{color:#ffb0a8}.success{color:#8fe3b2}@media(max-width:1000px){.content-grid{grid-template-columns:1fr}}
</style>
