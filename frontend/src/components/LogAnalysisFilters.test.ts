import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LogAnalysisFilters from "@/components/LogAnalysisFilters.vue";

describe("LogAnalysisFilters", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-30T02:00:00Z"));
  });

  afterEach(() => vi.useRealTimers());

  it("defaults to the recent three Beijing calendar days and exposes all hours", () => {
    const wrapper = mount(LogAnalysisFilters);

    expect((wrapper.get("[data-testid='filter-date-from']").element as HTMLInputElement).value).toBe("2026-09-28");
    expect((wrapper.get("[data-testid='filter-date-to']").element as HTMLInputElement).value).toBe("2026-09-30");
    expect(wrapper.get("[data-testid='filter-hour-from']").findAll("option")).toHaveLength(24);
    expect(wrapper.get("[data-testid='filter-hour-to']").findAll("option")).toHaveLength(24);
  });

  it("requires a package name and blocks ranges longer than seven calendar days", async () => {
    const wrapper = mount(LogAnalysisFilters);

    await wrapper.get("[data-testid='filter-query-existing']").trigger("click");
    expect(wrapper.emitted("query")).toBeUndefined();
    expect(wrapper.get("[data-testid='filter-error']").text()).toContain("包名");

    await wrapper.get("[data-testid='filter-package-name']").setValue("com.example.app");
    await wrapper.get("[data-testid='filter-date-from']").setValue("2026-09-01");
    await wrapper.get("[data-testid='filter-date-to']").setValue("2026-09-09");
    await wrapper.get("[data-testid='filter-query-existing']").trigger("click");

    expect(wrapper.emitted("query")).toBeUndefined();
    expect(wrapper.get("[data-testid='filter-error']").text()).toContain("7 天");
  });

  it("emits a complete scope for querying existing results without starting a parse job", async () => {
    const wrapper = mount(LogAnalysisFilters, {
      props: { modelValue: { package_name: "com.example.app" } },
    });

    await wrapper.get("[data-testid='filter-hour-from']").setValue("6");
    await wrapper.get("[data-testid='filter-hour-to']").setValue("18");
    await wrapper.get("[data-testid='filter-query-existing']").trigger("click");

    expect(wrapper.emitted("query")?.[0]?.[0]).toEqual({
      package_name: "com.example.app",
      date_from: "2026-09-28",
      hour_from: 6,
      date_to: "2026-09-30",
      hour_to: 18,
    });
    expect(wrapper.emitted("start-parse")).toBeUndefined();
  });
});
