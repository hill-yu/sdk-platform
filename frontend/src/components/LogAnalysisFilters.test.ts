import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import LogAnalysisFilters, {
  type LogAnalysisFilterValues,
} from "@/components/LogAnalysisFilters.vue";

const filters: LogAnalysisFilterValues = {
  date_from: "2026-08-01",
  date_to: "2026-08-07",
  package_name: "com.example.app",
  device_id: "device-1",
  log_level: "error",
};

describe("LogAnalysisFilters", () => {
  it("explains Beijing time, exact matching, and current effective conditions", () => {
    const wrapper = mount(LogAnalysisFilters, { props: { modelValue: filters } });

    expect(wrapper.text()).toContain("北京时间");
    expect(wrapper.text()).toContain("完全匹配");
    expect(wrapper.text()).toContain("com.example.app");
    expect(wrapper.text()).toContain("device-1");
    expect(wrapper.text()).toContain("error");
  });

  it("emits updated values and query, refresh, and reset actions", async () => {
    const wrapper = mount(LogAnalysisFilters, { props: { modelValue: filters } });

    await wrapper.get("[data-testid='filter-package-name']").setValue("com.example.next");
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual([
      { ...filters, package_name: "com.example.next" },
    ]);

    await wrapper.get("[data-testid='filter-query']").trigger("click");
    await wrapper.get("[data-testid='filter-refresh']").trigger("click");
    expect(wrapper.emitted("query")?.at(-1)).toEqual([{ ...filters, package_name: "com.example.next" }]);
    expect(wrapper.emitted("refresh")?.at(-1)).toEqual([{ ...filters, package_name: "com.example.next" }]);

    await wrapper.get("[data-testid='filter-reset']").trigger("click");
    expect(wrapper.emitted("reset")?.at(-1)).toEqual([{
      date_from: "",
      date_to: "",
      package_name: "",
      device_id: "",
      log_level: "",
    }]);
  });

  it("shows applied conditions separately from an unsubmitted draft", async () => {
    const wrapper = mount(LogAnalysisFilters, {
      props: {
        modelValue: filters,
        appliedValue: filters,
      },
    });

    await wrapper.get("[data-testid='filter-package-name']").setValue("com.example.next");
    expect(wrapper.get("[data-testid='effective-conditions']").text()).toContain("com.example.app");
    expect(wrapper.get("[data-testid='effective-conditions']").text()).not.toContain("com.example.next");

    await wrapper.setProps({ appliedValue: { ...filters, package_name: "com.example.next" } });
    expect(wrapper.get("[data-testid='effective-conditions']").text()).toContain("com.example.next");
  });
});
