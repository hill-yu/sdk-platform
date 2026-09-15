import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import LogColumnSettings from "@/components/LogColumnSettings.vue";

const available = ["date", "package_name", "alias", "user_count", "flow_count"];
const defaults = ["date", "package_name", "alias"];

function mountSettings() {
  return mount(LogColumnSettings, {
    props: {
      availableColumns: available,
      defaultColumns: defaults,
      modelValue: defaults,
    },
  });
}

describe("LogColumnSettings", () => {
  it("preserves the committed order of valid columns", () => {
    const wrapper = mount(LogColumnSettings, {
      props: {
        availableColumns: available,
        defaultColumns: defaults,
        modelValue: ["package_name", "alias", "date"],
      },
    });

    expect(wrapper.findAll("[data-testid$='-visible'] span:first-child").map((node) => node.text())).toEqual([
      "package_name",
      "alias",
      "date",
    ]);
  });

  it("keeps date and package_name visible while adding, removing, and reordering columns", async () => {
    const wrapper = mountSettings();

    expect(wrapper.get("[data-testid='column-date-remove']").attributes("disabled")).toBeDefined();
    expect(wrapper.get("[data-testid='column-package_name-remove']").attributes("disabled")).toBeDefined();

    await wrapper.get("[data-testid='column-add-user_count']").trigger("click");
    expect(wrapper.findAll("[data-testid='column-user_count-visible']")).toHaveLength(1);

    await wrapper.get("[data-testid='column-alias-remove']").trigger("click");
    expect(wrapper.findAll("[data-testid='column-alias-visible']")).toHaveLength(0);

    await wrapper.get("[data-testid='column-user_count-up']").trigger("click");
    expect(wrapper.findAll("[data-testid$='-visible'] span:first-child").map((node) => node.text())).toEqual([
      "date",
      "user_count",
      "package_name",
    ]);
  });

  it("restores defaults and emits only the draft when saving", async () => {
    const wrapper = mountSettings();

    await wrapper.get("[data-testid='column-add-user_count']").trigger("click");
    expect(wrapper.emitted("update:modelValue")).toBeUndefined();

    await wrapper.get("[data-testid='column-settings-save']").trigger("click");
    expect(wrapper.emitted("save")).toEqual([[defaults.concat("user_count")]]);

    await wrapper.get("[data-testid='column-settings-reset']").trigger("click");
    expect(wrapper.findAll("[data-testid$='-visible'] span:first-child").map((node) => node.text())).toEqual(defaults);
  });

  it("keeps the local selection visible when saving fails or is in progress", async () => {
    const wrapper = mount(LogColumnSettings, {
      props: {
        availableColumns: available,
        defaultColumns: defaults,
        modelValue: defaults,
        saveError: "保存失败",
      },
    });

    await wrapper.get("[data-testid='column-add-flow_count']").trigger("click");
    expect(wrapper.findAll("[data-testid='column-flow_count-visible']")).toHaveLength(1);
    await wrapper.setProps({ saving: true });
    expect(wrapper.get("[data-testid='column-settings-save']").attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("保存失败");
  });
});
