import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getMetricConfigs, getMetricOverview, getMetricTargets } from "@/api/logMetrics";
import LogMetricsPanel from "@/components/LogMetricsPanel.vue";

vi.mock("@/api/logMetrics", () => ({
  getMetricConfigs: vi.fn(),
  getMetricOverview: vi.fn(),
  getMetricTargets: vi.fn(),
}));

const scope = { package_name: "com.example.app", date_from: "2026-09-28", hour_from: 0, date_to: "2026-09-30", hour_to: 23 };
const successJob = { id: 11, package_name: scope.package_name, range_start: "2026-09-27T16:00:00Z", range_end: "2026-09-30T15:59:59Z", snapshot_end_utc: "2026-09-30T15:59:59Z", status: "success" as const, total_count: 10, processed_count: 10, h1_count: 4, failed_h1_count: 0, no_h1_count: 0 };

describe("LogMetricsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getMetricOverview).mockResolvedValue({ data: { code: 0, data: {
      declaration_count: 10, planned_click_count: 10, actual_click_count: 8, response_success_count: 6,
      plan_mismatch_count: 2, interstitial_presentation_count: 4, interstitial_click_count: 2,
      interstitial_close_count: 1, interstitial_close_rate: null, interstitial_non_close_click_rate: 0.5,
      target_breakdown: {},
    } } } as never);
    vi.mocked(getMetricConfigs).mockResolvedValue({ data: { code: 0, data: { total: 2, items: [
      { config_id: "unknown", declaration_count: 3, share: null },
      { config_id: 8, declaration_count: 7, share: 0.7 },
    ] } } } as never);
    vi.mocked(getMetricTargets).mockResolvedValue({ data: { code: 0, data: { items: [
      { target_kind: "web_element", planned_count: 5, actual_count: 4, success_count: 3, failure_count: 1, actual_rate: 0.8, success_rate: 0.75, failure_rate: 0.25 },
    ] } } } as never);
  });

  it("loads scoped metrics, separates planned/actual/success, and shows null as a dash", async () => {
    const wrapper = mount(LogMetricsPanel, { props: { scope, job: successJob } });
    await flushPromises();

    expect(getMetricOverview).toHaveBeenCalledWith({ ...scope, snapshot_end_utc: successJob.snapshot_end_utc });
    expect(getMetricConfigs).toHaveBeenCalledWith({ ...scope, snapshot_end_utc: successJob.snapshot_end_utc });
    expect(wrapper.get("[data-testid='planned-click-count']").text()).toBe("10");
    expect(wrapper.get("[data-testid='actual-click-count']").text()).toBe("8");
    expect(wrapper.get("[data-testid='response-success-count']").text()).toBe("6");
    expect(wrapper.get("[data-testid='interstitial-close-rate']").text()).toBe("-");
    expect(wrapper.get("[data-testid='unknown-config']").text()).toContain("unknown");
    expect(wrapper.get("[data-testid='plan-mismatch-alert']").text()).toContain("2");
  });

  it("uses the same scope for target dimensions and emits a failure selection", async () => {
    vi.mocked(getMetricTargets).mockResolvedValue({ data: { code: 0, data: { items: [
      { target_kind: "web_element", planned_count: 5, actual_count: 4, success_count: 3, failure_count: 1, actual_rate: 0.8, success_rate: 0.75, failure_rate: 0.25 },
      { target_kind: "banner", planned_count: 1, actual_count: 1, success_count: 1, failure_count: 0, actual_rate: 1, success_rate: 1, failure_rate: 0 },
      { target_kind: "anchored", planned_count: 1, actual_count: 0, success_count: 0, failure_count: 1, actual_rate: 0, success_rate: 0, failure_rate: 1 },
    ] } } } as never);
    const wrapper = mount(LogMetricsPanel, { props: { scope, job: successJob } });
    await flushPromises();
    await wrapper.get("[data-testid='target-tab-ad-area']").trigger("click");
    await flushPromises();

    expect(getMetricTargets).toHaveBeenLastCalledWith({ ...scope, snapshot_end_utc: successJob.snapshot_end_utc });
    await wrapper.get("[data-testid='metric-failure-button']").trigger("click");
    expect(wrapper.emitted("failure-select")?.[0]?.[0]).toEqual({ target_kind: "ad_area" });
  });

  it("normalizes raw target rows into web-element and ad-area views and recomputes rates", async () => {
    vi.mocked(getMetricTargets).mockResolvedValue({ data: { code: 0, data: { items: [
      { target_kind: "banner", planned_count: 10, actual_count: 4, success_count: 3, failure_count: 1, actual_rate: 0.4, success_rate: 0.3, failure_rate: 0.1 },
      { target_kind: "anchored", planned_count: 6, actual_count: 2, success_count: 1, failure_count: 1, actual_rate: 0.33, success_rate: 0.16, failure_rate: 0.16 },
      { target_kind: "web_element", planned_count: 7, actual_count: 5, success_count: 4, failure_count: 1, actual_rate: 0.71, success_rate: 0.57, failure_rate: 0.14 },
      { target_kind: "other", planned_count: 99, actual_count: 99, success_count: 99, failure_count: 0, actual_rate: 1, success_rate: 1, failure_rate: 0 },
    ] } } } as never);
    const wrapper = mount(LogMetricsPanel, { props: { scope, job: successJob } });
    await flushPromises();

    expect(wrapper.get("[data-testid='target-row']").text()).toContain("7");
    await wrapper.get("[data-testid='target-tab-ad-area']").trigger("click");
    await flushPromises();
    const row = wrapper.get("[data-testid='target-row']");
    expect(row.text()).toContain("16");
    expect(row.text()).toContain("6");
    expect(row.text()).toContain("4");
    expect(row.text()).toContain("2");
    expect(row.text()).toContain("38%");
    expect(row.text()).toContain("25%");
    expect(row.text()).toContain("13%");
  });

  it("keeps only the newest scope and target-tab responses", async () => {
    const deferred = <T,>() => {
      let resolve!: (value: T) => void;
      const promise = new Promise<T>((nextResolve) => { resolve = nextResolve; });
      return { promise, resolve };
    };
    const overviewA = deferred<unknown>();
    const overviewB = deferred<unknown>();
    vi.mocked(getMetricOverview).mockImplementation((value) => value.package_name === "a" ? overviewA.promise as never : overviewB.promise as never);
    vi.mocked(getMetricConfigs).mockResolvedValue({ data: { code: 0, data: { total: 0, items: [] } } } as never);
    vi.mocked(getMetricTargets).mockResolvedValue({ data: { code: 0, data: { items: [{ target_kind: "web_element", planned_count: 2, actual_count: 1, success_count: 1, failure_count: 0, actual_rate: 0.5, success_rate: 0.5, failure_rate: 0 }] } } } as never);
    const wrapper = mount(LogMetricsPanel, { props: { scope: { ...scope, package_name: "a" }, job: { ...successJob, package_name: "a" } } });
    await wrapper.setProps({ scope: { ...scope, package_name: "b" } });
    overviewB.resolve({ data: { code: 0, data: { ...({ declaration_count: 2, planned_click_count: 2, actual_click_count: 1, response_success_count: 1, plan_mismatch_count: 0, interstitial_presentation_count: 0, interstitial_click_count: 0, interstitial_close_count: 0, interstitial_close_rate: null, interstitial_non_close_click_rate: null, target_breakdown: {} }) } } });
    await flushPromises();
    overviewA.resolve({ data: { code: 0, data: { declaration_count: 1, planned_click_count: 1, actual_click_count: 0, response_success_count: 0, plan_mismatch_count: 0, interstitial_presentation_count: 0, interstitial_click_count: 0, interstitial_close_count: 0, interstitial_close_rate: null, interstitial_non_close_click_rate: null, target_breakdown: {} } } });
    await flushPromises();
    expect(wrapper.get("[data-testid='planned-click-count']").text()).toBe("2");
  });

  it("keeps only the last target-tab response when tabs are switched quickly", async () => {
    const deferred = <T,>() => {
      let resolve!: (value: T) => void;
      const promise = new Promise<T>((nextResolve) => { resolve = nextResolve; });
      return { promise, resolve };
    };
    const web = deferred<unknown>();
    const adArea = deferred<unknown>();
    vi.mocked(getMetricTargets).mockReturnValueOnce(web.promise as never).mockReturnValueOnce(adArea.promise as never);
    const wrapper = mount(LogMetricsPanel, { props: { scope, job: successJob } });
    await flushPromises();
    await wrapper.get("[data-testid='target-tab-ad-area']").trigger("click");
    adArea.resolve({ data: { code: 0, data: { items: [{ target_kind: "banner", planned_count: 6, actual_count: 2, success_count: 1, failure_count: 1, actual_rate: 0.33, success_rate: 0.16, failure_rate: 0.16 }] } } });
    await flushPromises();
    web.resolve({ data: { code: 0, data: { items: [{ target_kind: "web_element", planned_count: 99, actual_count: 99, success_count: 99, failure_count: 0, actual_rate: 1, success_rate: 1, failure_rate: 0 }] } } });
    await flushPromises();
    expect(wrapper.get("[data-testid='target-row']").text()).toContain("6");
    expect(wrapper.get("[data-testid='target-row']").text()).not.toContain("99");
  });

  it("passes a selected numeric config to the failure event and keeps unknown non-selectable", async () => {
    const wrapper = mount(LogMetricsPanel, { props: { scope, job: successJob } });
    await flushPromises();
    await wrapper.get("[data-testid='config-select-8']").trigger("click");
    expect(wrapper.get("[data-testid='config-select-unknown']").attributes("disabled")).toBeDefined();
    await wrapper.get("[data-testid='metric-failure-button']").trigger("click");
    expect(wrapper.emitted("failure-select")?.at(-1)?.[0]).toEqual({ target_kind: "web_element", config_id: 8 });
  });

  it("does not read formal metrics before a successful parse", async () => {
    const wrapper = mount(LogMetricsPanel, { props: { scope, job: { ...successJob, status: "running" } } });
    await flushPromises();
    expect(getMetricOverview).not.toHaveBeenCalled();
    expect(wrapper.get("[data-testid='metrics-status']").text()).toContain("解析进行中");
  });
});
