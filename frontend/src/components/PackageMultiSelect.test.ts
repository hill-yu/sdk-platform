import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const searchLogPackages = vi.hoisted(() => vi.fn());
vi.mock("@/api/logExports", () => ({ searchLogPackages }));
import PackageMultiSelect from "@/components/PackageMultiSelect.vue";

describe("PackageMultiSelect", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    searchLogPackages.mockReset().mockResolvedValue({ data: { items: ["com.tech.a", "com.tech.b"] } });
  });

  it("searches, selects without duplicates, and removes packages", async () => {
    const wrapper = mount(PackageMultiSelect, { props: { modelValue: [] } });
    await wrapper.get("[data-testid='package-search']").setValue("tech");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    expect(searchLogPackages).toHaveBeenCalledWith("tech");
    await wrapper.get("[data-testid='package-option']").trigger("click");
    expect(wrapper.emitted("update:modelValue")?.[0]).toEqual([["com.tech.a"]]);
    await wrapper.setProps({ modelValue: ["com.tech.a"] });
    await wrapper.get("[data-testid='remove-package']").trigger("click");
    expect(wrapper.emitted("update:modelValue")?.[1]).toEqual([[]]);
  });

  it("ignores an older search response", async () => {
    let resolveOld!: (value: unknown) => void;
    const oldRequest = new Promise((resolve) => { resolveOld = resolve; });
    searchLogPackages.mockReturnValueOnce(oldRequest).mockResolvedValueOnce({ data: { items: ["new.package"] } });
    const wrapper = mount(PackageMultiSelect, { props: { modelValue: [] } });
    await wrapper.get("[data-testid='package-search']").setValue("old");
    await vi.advanceTimersByTimeAsync(300);
    await wrapper.get("[data-testid='package-search']").setValue("new");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    resolveOld({ data: { items: ["old.package"] } });
    await flushPromises();
    expect(wrapper.text()).toContain("new.package");
    expect(wrapper.text()).not.toContain("old.package");
  });
});
