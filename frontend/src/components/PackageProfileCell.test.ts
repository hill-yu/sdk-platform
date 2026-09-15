import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

const { putPackageProfile } = vi.hoisted(() => ({ putPackageProfile: vi.fn() }));

vi.mock("@/api/logAnalysis", () => ({ putPackageProfile }));

import PackageProfileCell from "@/components/PackageProfileCell.vue";

describe("PackageProfileCell", () => {
  it("supports first creation and clearing an empty profile value", async () => {
    putPackageProfile.mockResolvedValue({
      data: { package_name: "com.example.app", alias: "", company: "", account: "" },
    });
    const wrapper = mount(PackageProfileCell, {
      props: { packageName: "com.example.app", field: "alias", modelValue: null },
    });

    expect(wrapper.get("[data-testid='profile-value']").text()).toBe("");
    await wrapper.get("[data-testid='profile-edit']").trigger("click");
    await wrapper.get("[data-testid='profile-input']").setValue("");
    await wrapper.get("[data-testid='profile-save']").trigger("click");
    await flushPromises();

    expect(putPackageProfile).toHaveBeenCalledWith("com.example.app", { alias: "" });
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual([""]);
  });

  it("edits and saves a value, disabling duplicate actions while saving", async () => {
    let resolveSave!: (value: unknown) => void;
    putPackageProfile.mockReturnValue(new Promise((resolve) => { resolveSave = resolve; }));
    const wrapper = mount(PackageProfileCell, {
      props: { packageName: "com.example.app", field: "company", modelValue: "Old Co" },
    });

    await wrapper.get("[data-testid='profile-edit']").trigger("click");
    await wrapper.get("[data-testid='profile-input']").setValue("New Co");
    await wrapper.get("[data-testid='profile-save']").trigger("click");
    expect(wrapper.get("[data-testid='profile-input']").attributes("disabled")).toBeDefined();
    expect(wrapper.get("[data-testid='profile-save']").attributes("disabled")).toBeDefined();

    resolveSave({ data: { package_name: "com.example.app", alias: "", company: "New Co", account: "" } });
    await flushPromises();
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual(["New Co"]);
  });

  it("keeps the edited value and error state when saving fails", async () => {
    putPackageProfile.mockRejectedValue(new Error("保存失败"));
    const wrapper = mount(PackageProfileCell, {
      props: { packageName: "com.example.app", field: "account", modelValue: null },
    });

    await wrapper.get("[data-testid='profile-edit']").trigger("click");
    await wrapper.get("[data-testid='profile-input']").setValue("account-1");
    await wrapper.get("[data-testid='profile-save']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-testid='profile-input']").element).toHaveProperty("value", "account-1");
    expect(wrapper.text()).toContain("保存失败");
    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
  });

  it("ignores an old save response after package or field changes", async () => {
    let resolveSave!: (value: unknown) => void;
    putPackageProfile.mockReturnValue(new Promise((resolve) => { resolveSave = resolve; }));
    const wrapper = mount(PackageProfileCell, {
      props: { packageName: "com.example.app", field: "alias", modelValue: "Old" },
    });

    await wrapper.get("[data-testid='profile-edit']").trigger("click");
    await wrapper.get("[data-testid='profile-input']").setValue("New");
    await wrapper.get("[data-testid='profile-save']").trigger("click");
    await wrapper.setProps({ packageName: "com.example.other", field: "company" });

    resolveSave({ data: { package_name: "com.example.app", alias: "New", company: "", account: "" } });
    await flushPromises();

    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
    expect(wrapper.emitted("saved")).toBeUndefined();
  });
});
