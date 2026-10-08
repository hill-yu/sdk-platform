import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import LogParseTaskPanel from "@/components/LogParseTaskPanel.vue";

const scope = {
  package_name: "com.example.app",
  date_from: "2026-09-28",
  hour_from: 0,
  date_to: "2026-09-30",
  hour_to: 23,
};

const runningJob = {
  id: 11,
  package_name: scope.package_name,
  range_start: "2026-09-28T00:00:00+08:00",
  range_end: "2026-09-30T23:59:59+08:00",
  status: "running" as const,
  total_count: 10,
  processed_count: 2,
  h1_count: 4,
  failed_h1_count: 0,
  no_h1_count: 0,
};

describe("LogParseTaskPanel", () => {
  it("emits the latest draft for LogViewer to validate instead of posting itself", async () => {
    const wrapper = mount(LogParseTaskPanel, {
      props: {
        draftScope: scope,
        appliedScope: null,
        job: null,
      },
    });

    await wrapper.get("[data-testid='start-parse']").trigger("click");

    expect(wrapper.emitted("request-parse")).toEqual([[scope]]);
  });

  it("renders status and progress supplied by LogViewer", () => {
    const wrapper = mount(LogParseTaskPanel, {
      props: { draftScope: scope, appliedScope: scope, job: runningJob },
    });
    expect(wrapper.get("[data-testid='parse-status']").text()).toContain("解析中");
    expect(wrapper.get("[data-testid='parse-status']").text()).toContain("2 / 10");
  });

  it("does not emit when parsing is disabled", async () => {
    const wrapper = mount(LogParseTaskPanel, {
      props: { draftScope: { ...scope, package_name: "" }, appliedScope: null, job: null, disabled: true },
    });
    expect(wrapper.get("[data-testid='start-parse']").attributes("disabled")).toBeDefined();
    expect(wrapper.emitted("request-parse")).toBeUndefined();
  });

  it("keeps scope changes presentational until the user starts parsing", async () => {
    const wrapper = mount(LogParseTaskPanel, { props: { draftScope: scope, appliedScope: scope, job: null } });
    await wrapper.setProps({ draftScope: { ...scope, package_name: "com.example.next" } });
    expect(wrapper.emitted("request-parse")).toBeUndefined();
  });
});
