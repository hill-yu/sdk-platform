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

describe("LogMetricsPanel", () => {
  beforeEach(() => {
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
    const wrapper = mount(LogMetricsPanel, { props: { scope } });
    await flushPromises();

    expect(getMetricOverview).toHaveBeenCalledWith(scope);
    expect(getMetricConfigs).toHaveBeenCalledWith(scope);
    expect(wrapper.get("[data-testid='planned-click-count']").text()).toBe("10");
    expect(wrapper.get("[data-testid='actual-click-count']").text()).toBe("8");
    expect(wrapper.get("[data-testid='response-success-count']").text()).toBe("6");
    expect(wrapper.get("[data-testid='interstitial-close-rate']").text()).toBe("-");
    expect(wrapper.get("[data-testid='unknown-config']").text()).toContain("unknown");
    expect(wrapper.get("[data-testid='plan-mismatch-alert']").text()).toContain("2");
  });

  it("uses the same scope for target dimensions and emits a failure selection", async () => {
    const wrapper = mount(LogMetricsPanel, { props: { scope } });
    await flushPromises();
    await wrapper.get("[data-testid='target-tab-ad-area']").trigger("click");
    await flushPromises();

    expect(getMetricTargets).toHaveBeenLastCalledWith({ ...scope, target_kind: "ad_area" });
    await wrapper.get("[data-testid='metric-failure-button']").trigger("click");
    expect(wrapper.emitted("failure-select")?.[0]?.[0]).toEqual({ target_kind: "ad_area" });
  });
});
