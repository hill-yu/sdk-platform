import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createConfig: vi.fn(),
  getConfig: vi.fn(),
  getConfigs: vi.fn(),
  publishConfig: vi.fn(),
  rollbackConfig: vi.fn(),
  updateConfig: vi.fn(),
}));
vi.mock("@/api/config", () => api);

import ConfigManager from "@/views/ConfigManager.vue";

const TreeEditorStub = defineComponent({
  props: { modelValue: { required: true }, disabled: Boolean },
  emits: ["update:modelValue", "validation-change"],
  template: `
    <div data-testid="tree-editor" :data-disabled="String(disabled)">
      <pre data-testid="tree-value">{{ JSON.stringify(modelValue) }}</pre>
      <button data-testid="replace-tree-value" @click="$emit('update:modelValue', { updated: true })">replace</button>
      <button data-testid="invalidate-tree" @click="$emit('validation-change', false)">invalid</button>
      <button data-testid="validate-tree" @click="$emit('validation-change', true)">valid</button>
    </div>
  `,
});

type ConfigData = {
  mainConfig: unknown;
  newTouchConfig: unknown;
  newTextRuleConfig: unknown;
};

const firstData: ConfigData = {
  mainConfig: { source: "main-one" },
  newTouchConfig: { source: "touch-one" },
  newTextRuleConfig: { source: "text-one" },
};
const secondData: ConfigData = {
  mainConfig: { source: "main-two" },
  newTouchConfig: { source: "touch-two" },
  newTextRuleConfig: { source: "text-two" },
};

function item(id: number, status = "draft") {
  return { id, package_name: `com.example.${id}`, version: `v${id}`, status, updated_at: `before-${id}` };
}

function detail(id: number, configData: ConfigData, status = "draft", overrides: Record<string, unknown> = {}) {
  return { ...item(id, status), config_data: configData, change_log: `change-${id}`, ...overrides };
}

function listResponse({ published = [], drafts = [item(1), item(2)], history = [] }: {
  published?: ReturnType<typeof item>[];
  drafts?: ReturnType<typeof item>[];
  history?: ReturnType<typeof item>[];
} = {}) {
  api.getConfigs.mockResolvedValue({ data: { published, drafts, history } });
}

async function mountManager() {
  const wrapper = mount(ConfigManager, {
    global: { stubs: { ConfigTreeEditor: TreeEditorStub } },
  });
  await flushPromises();
  return wrapper;
}

function treeValue(wrapper: Awaited<ReturnType<typeof mountManager>>) {
  return JSON.parse(wrapper.get("[data-testid='tree-value']").text());
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

function publishButton(wrapper: Awaited<ReturnType<typeof mountManager>>) {
  const button = wrapper.findAll(".actions button").find((candidate) => candidate.text() === "发布");
  if (!button) throw new Error("missing publish button");
  return button;
}

describe("ConfigManager tree editing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listResponse();
    api.getConfig.mockImplementation((id: number) => Promise.resolve({
      data: id === 1 ? detail(1, firstData) : detail(2, secondData),
    }));
    api.updateConfig.mockResolvedValue({ data: {} });
    api.publishConfig.mockResolvedValue({ data: {} });
  });

  it("starts on mainConfig, switches fixed files, and only replaces the active root", async () => {
    const wrapper = await mountManager();

    expect(wrapper.get("[data-testid='config-file-tab'].active").text()).toBe("mainConfig");
    expect(treeValue(wrapper)).toEqual(firstData.mainConfig);

    await wrapper.findAll("[data-testid='config-file-tab']")[1].trigger("click");
    expect(treeValue(wrapper)).toEqual(firstData.newTouchConfig);
    await wrapper.get("[data-testid='replace-tree-value']").trigger("click");
    expect(treeValue(wrapper)).toEqual({ updated: true });

    await wrapper.findAll("[data-testid='config-file-tab']")[0].trigger("click");
    expect(treeValue(wrapper)).toEqual(firstData.mainConfig);
    await wrapper.findAll("[data-testid='config-file-tab']")[1].trigger("click");
    expect(treeValue(wrapper)).toEqual({ updated: true });
  });

  it("resets the active file to mainConfig when another config is selected", async () => {
    const wrapper = await mountManager();
    await wrapper.findAll("[data-testid='config-file-tab']")[2].trigger("click");
    expect(treeValue(wrapper)).toEqual(firstData.newTextRuleConfig);

    await wrapper.findAll(".list-item")[1].trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-testid='config-file-tab'].active").text()).toBe("mainConfig");
    expect(treeValue(wrapper)).toEqual(secondData.mainConfig);
  });

  it("keeps the latest selected config when an older detail request resolves last", async () => {
    const first = deferred<{ data: ReturnType<typeof detail> }>();
    const second = deferred<{ data: ReturnType<typeof detail> }>();
    api.getConfig.mockReset();
    api.getConfig.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const wrapper = mount(ConfigManager, {
      global: { stubs: { ConfigTreeEditor: TreeEditorStub } },
    });
    await flushPromises();

    await wrapper.findAll(".list-item")[1].trigger("click");
    second.resolve({ data: detail(2, secondData, "draft", { change_log: "latest change" }) });
    await flushPromises();
    await wrapper.get("[data-testid='json-mode']").trigger("click");
    expect(JSON.parse(wrapper.get<HTMLTextAreaElement>("[data-testid='json-editor']").element.value)).toEqual(secondData);
    await wrapper.get("[data-testid='tree-mode']").trigger("click");
    await wrapper.findAll("[data-testid='config-file-tab']")[1].trigger("click");
    await wrapper.get("[data-testid='invalidate-tree']").trigger("click");
    first.resolve({ data: detail(1, firstData, "draft", { change_log: "stale change" }) });
    await flushPromises();

    expect(wrapper.findAll(".list-item")[1].classes()).toContain("active");
    expect(treeValue(wrapper)).toEqual(secondData.newTouchConfig);
    expect(wrapper.get<HTMLInputElement>("input[placeholder='变更说明']").element.value).toBe("latest change");
    expect(wrapper.get("[data-testid='config-file-tab'].active").text()).toBe("newTouchConfig");
    await wrapper.get("[data-testid='json-mode']").trigger("click");
    expect(wrapper.find("[data-testid='json-editor']").exists()).toBe(false);
    expect(wrapper.get("[data-testid='error-feedback']").text()).toContain("树形配置");
  });

  it.each(["published", "archived"])("makes the tree editor and save action read-only for %s configs", async (status) => {
    const selected = item(3, status);
    listResponse(status === "published" ? { published: [selected], drafts: [] } : { drafts: [], history: [selected] });
    api.getConfig.mockResolvedValue({ data: detail(3, firstData, status) });

    const wrapper = await mountManager();

    expect(wrapper.get("[data-testid='tree-editor']").attributes("data-disabled")).toBe("true");
    expect(wrapper.get("[data-testid='save-config']").attributes("disabled")).toBeDefined();
  });

  it("blocks leaving an invalid tree, save, and publish until the draft is corrected", async () => {
    const wrapper = await mountManager();
    await wrapper.get("[data-testid='invalidate-tree']").trigger("click");

    await wrapper.findAll("[data-testid='config-file-tab']")[1].trigger("click");
    expect(wrapper.get("[data-testid='config-file-tab'].active").text()).toBe("mainConfig");
    expect(wrapper.find("[data-testid='tree-editor']").exists()).toBe(true);

    await wrapper.get("[data-testid='json-mode']").trigger("click");
    expect(wrapper.find("[data-testid='tree-editor']").exists()).toBe(true);

    await wrapper.get("[data-testid='save-config']").trigger("click");
    const publishButton = wrapper.findAll(".actions button").find((button) => button.text() === "发布");
    await publishButton!.trigger("click");
    await flushPromises();
    expect(api.updateConfig).not.toHaveBeenCalled();
    expect(api.publishConfig).not.toHaveBeenCalled();
    expect(wrapper.get("[data-testid='error-feedback']").text()).toContain("树形配置");

    await wrapper.get("[data-testid='validate-tree']").trigger("click");
    await wrapper.findAll("[data-testid='config-file-tab']")[1].trigger("click");
    expect(wrapper.get("[data-testid='config-file-tab'].active").text()).toBe("newTouchConfig");
    await wrapper.get("[data-testid='save-config']").trigger("click");
    await flushPromises();
    expect(api.updateConfig).toHaveBeenCalledOnce();
  });
});

describe("ConfigManager tree and JSON modes", () => {
  const specialData: ConfigData = {
    mainConfig: { "a.b": [{ "中文 字段": 1, "a[0]": true }] },
    newTouchConfig: {},
    newTextRuleConfig: {},
  };

  beforeEach(() => {
    vi.clearAllMocks();
    listResponse({ drafts: [item(1)] });
    api.getConfig.mockResolvedValue({ data: detail(1, specialData) });
    api.updateConfig.mockResolvedValue({ data: {} });
  });

  it("round trips special keys through JSON without changing data semantics", async () => {
    const wrapper = await mountManager();

    await wrapper.get("[data-testid='json-mode']").trigger("click");
    const textarea = wrapper.get<HTMLTextAreaElement>("[data-testid='json-editor']");
    expect(JSON.parse(textarea.element.value)).toEqual(specialData);
    await wrapper.get("[data-testid='tree-mode']").trigger("click");
    expect(treeValue(wrapper)).toEqual(specialData.mainConfig);
    await wrapper.get("[data-testid='json-mode']").trigger("click");
    expect(JSON.parse(wrapper.get<HTMLTextAreaElement>("[data-testid='json-editor']").element.value)).toEqual(specialData);
  });

  it.each([
    ["invalid JSON syntax", "{ invalid", "配置 JSON 格式错误"],
    ["a missing required root", JSON.stringify({ mainConfig: {}, newTouchConfig: {} }), "newTextRuleConfig"],
  ])("blocks JSON to tree switching for %s", async (_case, value, expectedMessage) => {
    const wrapper = await mountManager();
    await wrapper.get("[data-testid='json-mode']").trigger("click");
    await wrapper.get("[data-testid='json-editor']").setValue(value);

    await wrapper.get("[data-testid='tree-mode']").trigger("click");

    expect(wrapper.find("[data-testid='json-editor']").exists()).toBe(true);
    expect(wrapper.get("[data-testid='error-feedback']").text()).toContain(expectedMessage);
  });

  it("validates complete config_data before saving", async () => {
    const wrapper = await mountManager();
    await wrapper.get("[data-testid='json-mode']").trigger("click");
    await wrapper.get("[data-testid='json-editor']").setValue(JSON.stringify({ mainConfig: {}, newTouchConfig: {} }));

    await wrapper.get("[data-testid='save-config']").trigger("click");
    await flushPromises();

    expect(api.updateConfig).not.toHaveBeenCalled();
    expect(wrapper.get("[data-testid='error-feedback']").text()).toContain("newTextRuleConfig");
  });

  it("saves the complete three-file config and preserves timeout confirmation", async () => {
    const timeout = Object.assign(new Error("timeout of 60000ms exceeded"), { code: "ECONNABORTED" });
    api.updateConfig.mockRejectedValueOnce(timeout);
    api.getConfig
      .mockResolvedValueOnce({ data: detail(1, specialData) })
      .mockResolvedValueOnce({ data: detail(1, specialData, "draft", { updated_at: "after-save" }) });
    const wrapper = await mountManager();

    await wrapper.get("[data-testid='save-config']").trigger("click");
    await flushPromises();

    expect(api.updateConfig).toHaveBeenCalledWith(1, {
      config_data: specialData,
      change_log: "change-1",
    });
    expect(wrapper.get("[data-testid='success-feedback']").text()).toContain("已确认配置保存成功");
  });

  it("preserves publish timeout confirmation", async () => {
    const timeout = Object.assign(new Error("timeout of 60000ms exceeded"), { code: "ECONNABORTED" });
    api.publishConfig.mockRejectedValueOnce(timeout);
    api.getConfig
      .mockResolvedValueOnce({ data: detail(1, specialData) })
      .mockResolvedValueOnce({ data: detail(1, specialData, "published", { version: "v2" }) });
    const wrapper = await mountManager();

    const publishButton = wrapper.findAll(".actions button").find((button) => button.text() === "发布");
    expect(publishButton).toBeDefined();
    await publishButton!.trigger("click");
    await flushPromises();

    expect(api.publishConfig).toHaveBeenCalledWith(1);
    expect(wrapper.get("[data-testid='success-feedback']").text()).toContain("已确认配置发布成功");
  });

  it.each([
    ["invalid JSON syntax", "{ invalid", "配置 JSON 格式错误"],
    ["a missing required root", JSON.stringify({ mainConfig: {}, newTouchConfig: {} }), "newTextRuleConfig"],
  ])("blocks publishing %s and preserves the JSON input", async (_case, value, expectedMessage) => {
    const wrapper = await mountManager();
    await wrapper.get("[data-testid='json-mode']").trigger("click");
    await wrapper.get("[data-testid='json-editor']").setValue(value);

    await publishButton(wrapper).trigger("click");
    await flushPromises();

    expect(api.publishConfig).not.toHaveBeenCalled();
    expect(wrapper.get<HTMLTextAreaElement>("[data-testid='json-editor']").element.value).toBe(value);
    expect(wrapper.get("[data-testid='error-feedback']").text()).toContain(expectedMessage);
  });

  it("publishes after validating a complete JSON draft", async () => {
    const wrapper = await mountManager();
    const edited = { ...specialData, mainConfig: { edited: true } };
    await wrapper.get("[data-testid='json-mode']").trigger("click");
    await wrapper.get("[data-testid='json-editor']").setValue(JSON.stringify(edited));

    await publishButton(wrapper).trigger("click");
    await flushPromises();

    expect(api.publishConfig).toHaveBeenCalledWith(1);
  });
});
