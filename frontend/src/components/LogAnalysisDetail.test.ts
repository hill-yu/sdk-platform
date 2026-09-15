import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { LogDecodeItem } from "@/api/logAnalysis";
import LogAnalysisDetail from "@/components/LogAnalysisDetail.vue";

function makeDetail(overrides: Partial<LogDecodeItem> = {}): LogDecodeItem {
  return {
    event_id: 7,
    event_server_ts: "2026-08-13T10:00:00Z",
    record_index: 0,
    package_name: "com.example.app",
    device_id: null,
    status: "success",
    decoder_version: "1.0.0",
    decoded_timestamp: null,
    url: null,
    config_id: null,
    window: null,
    expected_click_count: 2,
    actual_click_count: 1,
    ad_click_count: 0,
    interstitial_presentation_count: 0,
    interstitial_click_count: 0,
    interstitial_close_count: 0,
    duration_ms: null,
    final_reason: null,
    is_success: null,
    decoded_payload: { event: "flow" },
    parse_error: null,
    parsed_at: null,
    extra: "raw-extra",
    ...overrides,
  };
}

describe("LogAnalysisDetail", () => {
  it("renders a horizontally scrollable detail table with null metrics as dashes", () => {
    const wrapper = mount(LogAnalysisDetail, {
      props: { items: [makeDetail()], total: 1, page: 1, pageSize: 20 },
    });

    expect(wrapper.findAll(".table-scroll")).toHaveLength(1);
    expect(wrapper.get("[data-testid='analysis-detail-row']").text()).toContain("2026-08-13 18:00:00");
    expect(wrapper.get("[data-testid='analysis-detail-row']").text()).toContain("-");
  });

  it("emits the selected row and displays structured JSON and original extra", async () => {
    const item = makeDetail();
    const wrapper = mount(LogAnalysisDetail, {
      props: { items: [item], selected: item, detail: item, total: 1, page: 1, pageSize: 20 },
    });

    await wrapper.get("[data-testid='analysis-detail-row']").trigger("click");
    expect(wrapper.emitted("select")).toEqual([[item]]);
    expect(wrapper.get("[data-testid='decoded-json']").text()).toContain('"event": "flow"');
    expect(wrapper.get("[data-testid='raw-extra']").text()).toBe("raw-extra");
  });

  it("emits page changes", async () => {
    const wrapper = mount(LogAnalysisDetail, {
      props: { items: [makeDetail()], total: 41, page: 1, pageSize: 20 },
    });

    await wrapper.get("[data-testid='detail-next-page']").trigger("click");
    expect(wrapper.emitted("page-change")).toEqual([[2]]);
  });
});
