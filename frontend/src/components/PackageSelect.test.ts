import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
});
