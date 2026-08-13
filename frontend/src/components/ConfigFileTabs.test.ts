import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ConfigFileTabs from "@/components/ConfigFileTabs.vue";

describe("ConfigFileTabs", () => {
  it("renders exactly the three fixed config files and marks the active tab", () => {
    const wrapper = mount(ConfigFileTabs, { props: { modelValue: "newTouchConfig" } });
    const tabs = wrapper.findAll("[data-testid='config-file-tab']");

    expect(tabs.map((tab) => tab.text())).toEqual([
      "mainConfig",
      "newTouchConfig",
      "newTextRuleConfig",
    ]);
    expect(tabs).toHaveLength(3);
    expect(tabs[1].classes()).toContain("active");
    expect(tabs[0].classes()).not.toContain("active");
  });

  it("emits the selected fixed config file", async () => {
    const wrapper = mount(ConfigFileTabs, { props: { modelValue: "mainConfig" } });

    await wrapper.findAll("[data-testid='config-file-tab']")[2].trigger("click");

    expect(wrapper.emitted("update:modelValue")).toEqual([["newTextRuleConfig"]]);
  });
});
