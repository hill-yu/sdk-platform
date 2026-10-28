import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, nextTick, ref } from "vue";

const searchLogPackages = vi.hoisted(() => vi.fn());
vi.mock("@/api/logExports", () => ({ searchLogPackages }));
import PackageSelect from "@/components/PackageSelect.vue";

describe("PackageSelect", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    searchLogPackages.mockReset().mockResolvedValue({ data: { items: ["com.example.a", "com.example.b"] } });
  });

  afterEach(() => vi.useRealTimers());

  it("loads candidates on focus and emits the complete selected package", async () => {
    const wrapper = mount(PackageSelect, { props: { modelValue: "", multiple: false } });
    await wrapper.get("[data-testid='package-select-input']").trigger("focus");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    expect(searchLogPackages).toHaveBeenCalledWith("");
    await wrapper.get("[data-testid='package-select-option']").trigger("click");
    expect(wrapper.emitted("update:modelValue")?.[0]).toEqual(["com.example.a"]);
  });

  it("renders the real admin envelope after a delayed package search", async () => {
    let resolve!: (value: unknown) => void;
    searchLogPackages.mockReturnValueOnce(new Promise((nextResolve) => { resolve = nextResolve; }));
    const wrapper = mount(PackageSelect, { props: { modelValue: "" } });
    const input = wrapper.get("[data-testid='package-select-input']");
    await input.trigger("focus");
    await vi.advanceTimersByTimeAsync(300);
    expect(wrapper.find("[data-testid='package-select-loading']").exists()).toBe(true);
    resolve({ code: 0, data: { items: ["com.slow-result"] } });
    await flushPromises();
    expect(wrapper.find("[data-testid='package-select-loading']").exists()).toBe(false);
    expect(wrapper.find("[data-package='com.slow-result']").exists()).toBe(true);
  });

  it("passes the selected candidate package to the event query", async () => {
    const getEvents = vi.fn().mockResolvedValue({ data: { total: 1, items: [] } });
    searchLogPackages.mockResolvedValueOnce({ code: 0, data: { items: ["com.real-candidate"] } });
    const host = defineComponent({
      components: { PackageSelect },
      setup() {
        const packageName = ref("");
        async function apply(value: string) {
          packageName.value = value;
          await getEvents({ event_type: "log", package_name: value });
        }
        return { packageName, apply };
      },
      template: `<PackageSelect v-model="packageName" @update:model-value="apply" />`,
    });
    const wrapper = mount(host);
    const input = wrapper.get("[data-testid='package-select-input']");
    await input.trigger("focus");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    await wrapper.get("[data-package='com.real-candidate']").trigger("click");
    await flushPromises();
    expect(getEvents).toHaveBeenCalledWith({ event_type: "log", package_name: "com.real-candidate" });
  });

  it("marks options with the themeable option class while preserving combobox semantics", async () => {
    const wrapper = mount(PackageSelect, { props: { modelValue: "", multiple: false } });
    await wrapper.get("[data-testid='package-select-input']").trigger("focus");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    const option = wrapper.get("[data-testid='package-select-option']");
    expect(option.classes()).toContain("package-option");
    expect(option.attributes("role")).toBe("option");
  });

  it("supports keyboard selection and escape closes the list", async () => {
    const wrapper = mount(PackageSelect, { props: { modelValue: "", multiple: false } });
    const input = wrapper.get("[data-testid='package-select-input']");
    await input.trigger("focus");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    await input.trigger("keydown", { key: "ArrowDown" });
    await input.trigger("keydown", { key: "Enter" });
    expect(wrapper.emitted("update:modelValue")?.[0]).toEqual(["com.example.a"]);
    await input.trigger("keydown", { key: "Escape" });
    expect(wrapper.find("[data-testid='package-select-option']").exists()).toBe(false);
  });

  it("does not let an older search overwrite a newer response", async () => {
    let resolveOld!: (value: unknown) => void;
    const old = new Promise((resolve) => { resolveOld = resolve; });
    searchLogPackages.mockReturnValueOnce(old).mockResolvedValueOnce({ data: { items: ["new.package"] } });
    const wrapper = mount(PackageSelect, { props: { modelValue: "", multiple: false } });
    const input = wrapper.get("[data-testid='package-select-input']");
    await input.trigger("focus");
    await vi.advanceTimersByTimeAsync(300);
    await input.setValue("new");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    resolveOld({ data: { items: ["old.package"] } });
    await flushPromises();
    expect(wrapper.text()).toContain("new.package");
    expect(wrapper.text()).not.toContain("old.package");
  });

  it("invalidates old options during the debounce window", async () => {
    const wrapper = mount(PackageSelect, { props: { modelValue: "", multiple: false } });
    const input = wrapper.get("[data-testid='package-select-input']");
    await input.trigger("focus");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    expect(wrapper.find("[data-testid='package-select-option']").exists()).toBe(true);
    await input.setValue("new");
    expect(wrapper.find("[data-testid='package-select-option']").exists()).toBe(false);
    expect(wrapper.find("[data-testid='package-select-loading']").exists()).toBe(true);
  });

  it("restores the applied value on escape and focus leaving the component", async () => {
    const wrapper = mount(PackageSelect, { props: { modelValue: "com.example.a", multiple: false } });
    const input = wrapper.get("[data-testid='package-select-input']");
    await input.trigger("focus");
    await input.setValue("com.example.b");
    await input.trigger("keydown", { key: "Escape" });
    expect((input.element as HTMLInputElement).value).toBe("com.example.a");
    expect(wrapper.find("[data-testid='package-select-option']").exists()).toBe(false);
    await input.trigger("focus");
    await input.setValue("com.example.c");
    await input.trigger("focusout", { relatedTarget: null });
    expect((input.element as HTMLInputElement).value).toBe("com.example.a");
    expect(wrapper.find("[data-testid='package-select-option']").exists()).toBe(false);
  });

  it("does not search or open when the parent changes the closed value", async () => {
    const wrapper = mount(PackageSelect, { props: { modelValue: "com.example.a", multiple: false } });
    searchLogPackages.mockClear();
    await wrapper.setProps({ modelValue: "com.example.b" });
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    expect((wrapper.get("[data-testid='package-select-input']").element as HTMLInputElement).value).toBe("com.example.b");
    expect(wrapper.find("[data-testid='package-select-option']").exists()).toBe(false);
    expect(searchLogPackages).not.toHaveBeenCalled();
  });

  it("supports multiple selection, de-duplicates, removes chips, and reports errors", async () => {
    searchLogPackages.mockRejectedValueOnce(new Error("search unavailable"));
    const wrapper = mount(PackageSelect, { props: { modelValue: ["com.example.a"], multiple: true } });
    const input = wrapper.get("[data-testid='package-select-input']");
    await input.trigger("focus");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    expect(wrapper.get("[data-testid='package-select-error']").text()).toContain("search unavailable");
    searchLogPackages.mockResolvedValueOnce({ data: { items: ["com.example.a", "com.example.b"] } });
    await wrapper.get("[data-testid='package-select-retry']").trigger("click");
    await vi.waitFor(() => expect(wrapper.find("[data-testid='package-select-loading']").exists()).toBe(false));
    await wrapper.get("[data-testid='package-select-option'][data-package='com.example.b']").trigger("click");
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual([["com.example.a", "com.example.b"]]);
    await wrapper.setProps({ modelValue: ["com.example.a", "com.example.b"] });
    await wrapper.get("[data-testid='package-select-option'][data-package='com.example.a']").trigger("click");
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual([["com.example.a", "com.example.b"]]);
    await wrapper.setProps({ modelValue: ["com.example.b"] });
    await wrapper.get("[data-testid='package-select-remove']").trigger("click");
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual([[]]);
  });

  it("shows a retry after a failed search and renders the next real envelope", async () => {
    searchLogPackages.mockRejectedValueOnce(new Error("search unavailable"));
    const wrapper = mount(PackageSelect, { props: { modelValue: "" } });
    const input = wrapper.get("[data-testid='package-select-input']");
    await input.trigger("focus");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    expect(wrapper.get("[data-testid='package-select-error']").text()).toContain("search unavailable");
    searchLogPackages.mockResolvedValueOnce({ code: 0, data: { items: ["com.retry-result"] } });
    await wrapper.get("[data-testid='package-select-retry']").trigger("click");
    await flushPromises();
    expect(wrapper.find("[data-package='com.retry-result']").exists()).toBe(true);
  });

  it("preserves free text on focusout and commits it on Enter", async () => {
    const wrapper = mount(PackageSelect, { props: { modelValue: "com.initial", allowFreeText: true } });
    const input = wrapper.get("[data-testid='package-select-input']");
    await input.trigger("focus");
    expect((input.element as HTMLInputElement).value).toBe("com.initial");
    await input.setValue("com.manual");
    await input.trigger("keydown", { key: "Enter" });
    expect((input.element as HTMLInputElement).value).toBe("com.manual");
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual(["com.manual"]);
    await input.trigger("focusout", { relatedTarget: null });
    expect((input.element as HTMLInputElement).value).toBe("com.manual");
  });

  it("does not swallow the first character after an outside click", async () => {
    const wrapper = mount(PackageSelect, { props: { modelValue: "" } });
    const input = wrapper.get("[data-testid='package-select-input']");
    document.body.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await input.trigger("focus");
    searchLogPackages.mockClear();
    await input.setValue("c");
    await nextTick();
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    expect(searchLogPackages).toHaveBeenCalledWith("c");
  });

  it("does not swallow the first character after Escape leaves the value unchanged", async () => {
    const wrapper = mount(PackageSelect, { props: { modelValue: "" } });
    const input = wrapper.get("[data-testid='package-select-input']");
    await input.trigger("focus");
    await input.trigger("keydown", { key: "Escape" });
    searchLogPackages.mockClear();
    await input.setValue("c");
    await nextTick();
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    expect(searchLogPackages).toHaveBeenCalledWith("c");
  });

  it("does not leave a suppression flag after selecting the already typed candidate", async () => {
    const wrapper = mount(PackageSelect, { props: { modelValue: "" } });
    const input = wrapper.get("[data-testid='package-select-input']");
    await input.trigger("focus");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    await input.setValue("com.example.a");
    await nextTick();
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    await wrapper.get("[data-package='com.example.a']").trigger("click");
    searchLogPackages.mockClear();
    await input.setValue("xom.example.a");
    await nextTick();
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    expect(searchLogPackages).toHaveBeenCalledWith("xom.example.a");
  });

  it.each([
    { label: "analysis/raw selection", allowFreeText: false },
    { label: "usage free text", allowFreeText: true },
  ])("restores initial candidates after clearing a selected package ($label)", async ({ allowFreeText }) => {
    searchLogPackages.mockImplementation(async (keyword: string) => ({ data: { items: keyword ? [`${keyword}.match`] : ["com.initial"] } }));
    const wrapper = mount(PackageSelect, { props: { modelValue: "", allowFreeText } });
    const input = wrapper.get("[data-testid='package-select-input']");
    await input.trigger("focus");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    await wrapper.get("[data-package='com.initial']").trigger("click");

    await input.trigger("focus");
    await input.trigger("keydown", { key: "a", ctrlKey: true });
    await input.setValue("");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();

    expect(searchLogPackages).toHaveBeenLastCalledWith("");
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual([""]);
    expect(wrapper.find("[data-package='com.initial']").exists()).toBe(true);
    expect(wrapper.find("[data-testid='package-select-empty']").exists()).toBe(false);
  });

  it("keeps the empty search visible when a late selected-package response resolves", async () => {
    let resolveSelected!: (value: unknown) => void;
    searchLogPackages.mockReset()
      .mockResolvedValueOnce({ data: { items: ["com.initial"] } })
      .mockReturnValueOnce(new Promise((resolve) => { resolveSelected = resolve; }))
      .mockResolvedValueOnce({ data: { items: ["com.initial"] } });
    const wrapper = mount(PackageSelect, { props: { modelValue: "" } });
    const input = wrapper.get("[data-testid='package-select-input']");
    await input.trigger("focus");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    await wrapper.get("[data-package='com.initial']").trigger("click");
    await input.trigger("focus");
    await input.setValue("com.initial");
    await vi.advanceTimersByTimeAsync(300);
    await input.setValue("");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    resolveSelected({ data: { items: ["com.selected-only"] } });
    await flushPromises();
    expect(wrapper.find("[data-package='com.initial']").exists()).toBe(true);
    expect(wrapper.find("[data-package='com.selected-only']").exists()).toBe(false);
  });
});
