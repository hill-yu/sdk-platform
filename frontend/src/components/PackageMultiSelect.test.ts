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
});
