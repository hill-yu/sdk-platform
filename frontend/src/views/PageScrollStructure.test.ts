import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/api/dashboard", () => ({
  getBreakdown: vi.fn().mockResolvedValue({ data: [] }),
  getEventFilterOptions: vi.fn().mockResolvedValue({ data: { package_names: [], sdk_versions: [] } }),
  getEvents: vi.fn().mockResolvedValue({ data: { total: 0, items: [] } }),
  getSummary: vi.fn().mockResolvedValue({ data: {} }),
  getTrend: vi.fn().mockResolvedValue({ data: { points: [] } }),
}));

vi.mock("@/api/config", () => ({
  getConfigs: vi.fn().mockResolvedValue({ data: { published: [], drafts: [], history: [] } }),
}));

vi.mock("@/api/version", () => ({
  getVersions: vi.fn().mockResolvedValue({ data: [] }),
  createVersion: vi.fn(),
  updateVersion: vi.fn(),
}));

vi.mock("@/api/logAnalysis", () => ({
  FORMAL_METRIC_COLUMN_MAPPING: {
    alias: "package_profile.alias",
    company: "package_profile.company",
    account: "package_profile.account",
    url: "config_distribution",
    expected_click_count: "declaration_and_planned_cards",
    actual_click_count: "actual_and_response_cards",
    ad_click_count: "ad_area_actual_card_and_target_table",
    interstitial_presentation_count: "interstitial_presentation_and_close_rate_cards",
    interstitial_click_count: "interstitial_non_close_click_rate_card",
    parse_failure_count: "failed_h1_card",
  },
  getLogAnalysisColumns: vi.fn().mockResolvedValue({ data: { available_columns: [], default_columns: [], columns: [] } }),
  getPackageProfile: vi.fn(),
  putLogAnalysisColumns: vi.fn(),
}));

import Dashboard from "@/views/Dashboard.vue";
import ConfigManager from "@/views/ConfigManager.vue";
import LogViewer from "@/views/LogViewer.vue";
import VersionManager from "@/views/VersionManager.vue";
import versionManagerSource from "@/views/VersionManager.vue?raw";

describe("page wide-content scroll boundaries", () => {
  it("keeps dashboard events inside table-scroll", async () => {
    const wrapper = mount(Dashboard, { global: { stubs: { TrendChart: true, StatCard: true } } });
    await flushPromises();
    expect(wrapper.find(".table-scroll").exists()).toBe(true);
  });

  it("keeps config editor grid structure", () => {
    const wrapper = mount(ConfigManager, { global: { stubs: { ConfigFileTabs: true, ConfigTreeEditor: true } } });
    expect(wrapper.find(".content-grid").exists()).toBe(true);
    expect(wrapper.find(".editor-panel").exists()).toBe(true);
  });

  it("keeps version table inside table-scroll", async () => {
    const wrapper = mount(VersionManager);
    await flushPromises();
    expect(wrapper.find(".table-scroll").exists()).toBe(true);
  });

  it("keeps the version dialog within the viewport and scrollable", () => {
    expect(versionManagerSource).toContain("max-height: calc(100dvh - 40px);");
    expect(versionManagerSource).toContain("overflow: auto;");
  });

  it("keeps analysis and raw log table containers", async () => {
    const wrapper = mount(LogViewer, { global: { stubs: {
      LogAnalysisDetail: true,
      LogAnalysisFilters: true,
      LogColumnSettings: true,
      PackageProfileCell: true,
      LogDetail: true,
      LogExportPanel: true,
    } } });
    expect(wrapper.find("[data-testid='metrics-panel']").exists()).toBe(true);
    await wrapper.get("[data-testid='raw-view-tab']").trigger("click");
    await flushPromises();
    expect(wrapper.find(".table-scroll").exists()).toBe(true);
  });
});
