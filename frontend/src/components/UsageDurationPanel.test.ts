import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getUsageDevices, getUsageSummary } from "@/api/usageDurations";
import UsageDurationPanel from "@/components/UsageDurationPanel.vue";

const searchUsagePackages = vi.hoisted(() => vi.fn());

vi.mock("@/api/usageDurations", () => ({
  getUsageDevices: vi.fn(),
  getUsageSummary: vi.fn(),
  searchUsagePackages,
}));

const summaryScope = { date_from: "2026-09-28", hour_from: 0, date_to: "2026-09-30", hour_to: 23 };
const bucketKeys = ["le_120", "121_300", "301_600", "601_899", "900_1199", "1200_1499", "ge_1500"] as const;

function makeItem(packageName: string, overrides: Record<string, unknown> = {}) {
  return {
    package_name: packageName,
    device_count: 3,
    total_duration_s: 900,
    average_duration_s: 300,
    total_duration_text: "15 分",
    total_duration_exact_text: "900 秒",
    average_duration_text: "5 分",
    average_duration_exact_text: "300 秒",
    buckets: bucketKeys.map((key, index) => ({
      key,
      interval_text: `${key} 区间`,
      count: index === 0 ? 1 : 0,
      count_text: index === 0 ? "1" : "0",
      share: index === 0 ? 0.333 : 0,
      share_text: index === 0 ? "33.3%" : "0.0%",
      total_duration_s: index === 0 ? 120 : 0,
      total_duration_text: index === 0 ? "2 分" : "0 秒",
      total_duration_exact_text: index === 0 ? "120 秒" : "0 秒",
    })),
    last_report_at: "2026-09-30T10:00:00+08:00",
    last_report_text: "2026-09-30 10:00",
    ...overrides,
  };
}

const multiPage = {
  total: 2,
  total_pages: 1,
  page: 1,
  page_size: 10,
  items: [makeItem("com.a"), makeItem("com.b", { device_count: 1 })],
};

function devicePage(page = 1, pageSize = 10, total = 25) {
  const count = Math.max(0, Math.min(pageSize, total - (page - 1) * pageSize));
  return {
    total,
    total_pages: Math.ceil(total / pageSize),
    page,
    page_size: pageSize,
    items: Array.from({ length: count }, (_, index) => ({
      package_name: "com.a",
      device_id: `device-${page}-${index}`,
      device_model: "Pixel",
      os: "14",
      duration_s: 270,
      duration_text: "4 分 30 秒",
      duration_exact_text: "270 秒",
      sdk_version: "1.0",
      app_version: "2.0",
      last_report_at: null,
      last_report_text: "-",
    })),
  };
}

describe("UsageDurationPanel", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-30T02:00:00Z"));
    vi.clearAllMocks();
    vi.mocked(getUsageSummary).mockResolvedValue({ data: { code: 0, data: multiPage } } as never);
    vi.mocked(getUsageDevices).mockResolvedValue({ data: { code: 0, data: devicePage(1, 10) } } as never);
    searchUsagePackages.mockResolvedValue({ data: { items: ["com.a", "com.b"] } });
  });

  afterEach(() => vi.useRealTimers());

  it("uses the usage-backed package combobox and keeps the typed draft separate", async () => {
    const wrapper = mount(UsageDurationPanel);
    const input = wrapper.get("[data-testid='usage-package-name']");
    await input.trigger("focus");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();

    expect(searchUsagePackages).toHaveBeenCalledWith("");
    expect(wrapper.find("[data-testid='usage-package-option']").exists()).toBe(true);
  });

  it("renders a six-column overview from backend display text without bucket columns", async () => {
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();

    expect(getUsageSummary).toHaveBeenCalledWith({ ...summaryScope, page: 1, page_size: 10 });
    expect(wrapper.findAll("[data-testid='usage-summary-header']")).toHaveLength(6);
    expect(wrapper.find("[data-testid='usage-summary-header-bucket']").exists()).toBe(false);
    expect(wrapper.get("[data-testid='usage-summary-row']").text()).toContain("15 分");
    expect(wrapper.get("[data-testid='usage-summary-row']").text()).toContain("2026-09-30 10:00");
  });

  it("auto-selects a single package and maps seven buckets without requesting devices", async () => {
    vi.mocked(getUsageSummary).mockResolvedValueOnce({
      data: { code: 0, data: { ...multiPage, total: 1, items: [multiPage.items[0]] } },
    } as never);
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();

    expect(wrapper.get("[data-testid='usage-selected-package']").text()).toContain("com.a");
    expect(wrapper.findAll("[data-testid='usage-bucket-row']")).toHaveLength(7);
    expect(getUsageDevices).not.toHaveBeenCalled();
  });

  it("selects a package for distribution and lazily requests devices only on the device tab", async () => {
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    await wrapper.get("[data-testid='usage-view-details-0']").trigger("click");
    expect(wrapper.findAll("[data-testid='usage-bucket-row']")).toHaveLength(7);
    expect(getUsageDevices).not.toHaveBeenCalled();

    await wrapper.get("[data-testid='usage-device-tab']").trigger("click");
    await flushPromises();
    expect(getUsageSummary).toHaveBeenCalledTimes(1);
    expect(getUsageDevices).toHaveBeenCalledWith({ ...summaryScope, package_name: "com.a", page: 1, page_size: 10 });
    expect(wrapper.find("[data-testid='usage-detail-table-scroll']").exists()).toBe(true);
    const pagination = wrapper.find("[data-testid='usage-detail-pagination']").element;
    expect(pagination.parentElement?.getAttribute("data-testid")).not.toBe("usage-detail-table-scroll");
    expect(pagination.closest("[data-testid='usage-device-panel']")).not.toBeNull();
  });

  it("paginates overview on the server and resets the page when changing page size", async () => {
    vi.mocked(getUsageSummary).mockImplementation(async (scope) => ({
      data: {
        code: 0,
        data: { total: 25, total_pages: scope.page_size === 50 ? 1 : 3, page: scope.page, page_size: scope.page_size, items: [makeItem(`com.page-${scope.page}`)] },
      },
    }) as never);
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    await wrapper.get("[data-testid='usage-summary-next']").trigger("click");
    await flushPromises();
    expect(getUsageSummary).toHaveBeenLastCalledWith({ ...summaryScope, page: 2, page_size: 10 });
    await wrapper.get("[data-testid='usage-summary-page-size']").setValue("50");
    await flushPromises();
    expect(getUsageSummary).toHaveBeenLastCalledWith({ ...summaryScope, page: 1, page_size: 50 });
  });

  it("paginates device rows with a maximum page size of fifty and keeps pagination outside scroll", async () => {
    vi.mocked(getUsageSummary).mockResolvedValueOnce({ data: { code: 0, data: { ...multiPage, total: 1, items: [multiPage.items[0]] } } } as never);
    vi.mocked(getUsageDevices).mockImplementation(async (scope) => ({ data: { code: 0, data: devicePage(scope.page, scope.page_size, 75) } }) as never);
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    await wrapper.get("[data-testid='usage-view-details-0']").trigger("click");
    await wrapper.get("[data-testid='usage-device-tab']").trigger("click");
    await flushPromises();
    await wrapper.get("[data-testid='usage-device-page-size']").setValue("50");
    await flushPromises();

    expect(getUsageDevices).toHaveBeenLastCalledWith({ ...summaryScope, package_name: "com.a", page: 1, page_size: 50 });
    expect(wrapper.findAll("[data-testid='usage-device-row']")).toHaveLength(50);
    expect(wrapper.findAll("[data-testid='usage-device-header']")).toHaveLength(7);
    expect(wrapper.get("[data-testid='usage-device-next']").element.hasAttribute("disabled")).toBe(false);
  });

  it("keeps the old selection and applied scope when a new query fails", async () => {
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    await wrapper.get("[data-testid='usage-view-details-0']").trigger("click");
    vi.mocked(getUsageSummary).mockRejectedValueOnce(new Error("query unavailable"));
    await wrapper.get("[data-testid='usage-package-name']").setValue("com.failed");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(wrapper.get("[data-testid='usage-selected-package']").text()).toContain("com.a");
    expect(wrapper.get("[data-testid='usage-applied-scope']").text()).not.toContain("com.failed");
    expect(wrapper.get("[data-testid='usage-error']").text()).toContain("query unavailable");
    vi.mocked(getUsageSummary).mockResolvedValueOnce({ data: { code: 0, data: { ...multiPage, total: 1, items: [makeItem("com.failed")] } } } as never);
    await wrapper.get("[data-testid='usage-retry']").trigger("click");
    await flushPromises();
    expect(getUsageSummary).toHaveBeenLastCalledWith({ ...summaryScope, package_name: "com.failed", page: 1, page_size: 10 });
    expect(wrapper.get("[data-testid='usage-applied-scope']").text()).toContain("com.failed");
  });

  it("refreshes the selected package distribution and invalidates old device rows", async () => {
    vi.mocked(getUsageSummary).mockResolvedValueOnce({ data: { code: 0, data: { ...multiPage, total: 1, items: [multiPage.items[0]] } } } as never);
    const refreshed = makeItem("com.a", { total_duration_text: "16 分", buckets: [makeItem("com.a").buckets[0], ...makeItem("com.a").buckets.slice(1)] });
    vi.mocked(getUsageDevices).mockResolvedValueOnce({ data: { code: 0, data: devicePage(1, 10, 1) } } as never);
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    await wrapper.get("[data-testid='usage-device-tab']").trigger("click");
    await flushPromises();
    expect(wrapper.find("[data-testid='usage-device-row']").exists()).toBe(true);

    vi.mocked(getUsageSummary).mockResolvedValueOnce({ data: { code: 0, data: { ...multiPage, total: 1, items: [refreshed] } } } as never);
    await wrapper.get("[data-testid='usage-refresh']").trigger("click");
    await flushPromises();
    expect(wrapper.get("[data-testid='usage-selected-package']").text()).toContain("com.a");
    await wrapper.get("[data-testid='usage-distribution-tab']").trigger("click");
    expect(wrapper.get("[data-testid='usage-bucket-row']").text()).toContain("2 分");
    expect(wrapper.find("[data-testid='usage-device-row']").exists()).toBe(false);
  });

  it("ignores an older device response after a newer device page request", async () => {
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    await wrapper.get("[data-testid='usage-view-details-0']").trigger("click");
    await wrapper.get("[data-testid='usage-device-tab']").trigger("click");
    await flushPromises();

    let resolvePageTwo!: (value: unknown) => void;
    let resolvePageOne!: (value: unknown) => void;
    vi.mocked(getUsageDevices)
      .mockReturnValueOnce(new Promise((resolve) => { resolvePageTwo = resolve; }) as never)
      .mockReturnValueOnce(new Promise((resolve) => { resolvePageOne = resolve; }) as never);
    await wrapper.get("[data-testid='usage-device-next']").trigger("click");
    await wrapper.get("[data-testid='usage-device-page-size']").setValue("50");
    resolvePageOne({ data: { code: 0, data: { ...devicePage(1, 50, 1), items: [{ ...devicePage(1, 50, 1).items[0], device_id: "new-device" }] } } });
    await flushPromises();
    resolvePageTwo({ data: { code: 0, data: { ...devicePage(2, 10, 25), items: [{ ...devicePage(2, 10, 25).items[0], device_id: "old-device" }] } } });
    await flushPromises();

    expect(wrapper.get("[data-testid='usage-device-row']").text()).toContain("new-device");
    expect(wrapper.get("[data-testid='usage-device-row']").text()).not.toContain("old-device");
  });

  it("keeps only the newest summary response and does not calculate display values in the component", async () => {
    let resolveInitial!: (value: unknown) => void;
    let resolveNew!: (value: unknown) => void;
    vi.mocked(getUsageSummary)
      .mockReturnValueOnce(new Promise((resolve) => { resolveInitial = resolve; }) as never)
      .mockReturnValueOnce(new Promise((resolve) => { resolveNew = resolve; }) as never);
    const wrapper = mount(UsageDurationPanel);
    await wrapper.get("[data-testid='usage-package-name']").setValue("com.b");
    await wrapper.get("form").trigger("submit");
    resolveNew({ data: { code: 0, data: { ...multiPage, items: [multiPage.items[1]] } } });
    await flushPromises();
    resolveInitial({ data: { code: 0, data: multiPage } });
    await flushPromises();

    expect(wrapper.get("[data-testid='usage-summary-row']").text()).toContain("com.b");
    expect(wrapper.get("[data-testid='usage-summary-row']").text()).not.toContain("com.a");
    wrapper.unmount();
  });

  it("shows an empty state without stale package detail and keeps refresh failures visible", async () => {
    vi.mocked(getUsageSummary).mockResolvedValueOnce({ data: { code: 0, data: { total: 0, total_pages: 0, page: 1, page_size: 10, items: [] } } } as never);
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    expect(wrapper.find("[data-testid='usage-empty']").exists()).toBe(true);
    expect(wrapper.find("[data-testid='usage-selected-package']").exists()).toBe(false);

    vi.mocked(getUsageSummary).mockRejectedValueOnce(new Error("refresh unavailable"));
    await wrapper.get("[data-testid='usage-refresh']").trigger("click");
    await flushPromises();
    expect(wrapper.get("[data-testid='usage-error']").text()).toContain("refresh unavailable");
    expect(wrapper.find("[data-testid='usage-retry']").exists()).toBe(true);
    vi.mocked(getUsageSummary).mockResolvedValueOnce({ data: { code: 0, data: { total: 0, total_pages: 0, page: 1, page_size: 10, items: [] } } } as never);
    await wrapper.get("[data-testid='usage-retry']").trigger("click");
    await flushPromises();
    expect(getUsageSummary).toHaveBeenLastCalledWith({ ...summaryScope, page: 1, page_size: 10 });
  });
});
