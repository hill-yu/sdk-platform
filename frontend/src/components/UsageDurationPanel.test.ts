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
const summary = {
  total: 2,
  page: 1,
  page_size: 20,
  items: [
    { package_name: "com.a", device_model: null, device_count: 3, total_duration_s: 1020, average_duration_s: 340, buckets: [
      { key: "le_120", count: 1, share: 0.333, total_duration_s: 120 }, { key: "121_300", count: 1, share: 0.333, total_duration_s: 300 }, { key: "301_600", count: 1, share: 0.333, total_duration_s: 600 }, { key: "601_899", count: 0, share: 0, total_duration_s: 0 }, { key: "900_1199", count: 0, share: 0, total_duration_s: 0 }, { key: "1200_1499", count: 0, share: 0, total_duration_s: 0 }, { key: "ge_1500", count: 0, share: 0, total_duration_s: 0 },
    ], last_report_at: "2026-09-30 10:00:00" },
    { package_name: "com.b", device_model: null, device_count: 1, total_duration_s: 1500, average_duration_s: 1500, buckets: [
      { key: "le_120", count: 0, share: 0, total_duration_s: 0 }, { key: "121_300", count: 0, share: 0, total_duration_s: 0 }, { key: "301_600", count: 0, share: 0, total_duration_s: 0 }, { key: "601_899", count: 0, share: 0, total_duration_s: 0 }, { key: "900_1199", count: 0, share: 0, total_duration_s: 0 }, { key: "1200_1499", count: 0, share: 0, total_duration_s: 0 }, { key: "ge_1500", count: 1, share: 1, total_duration_s: 1500 },
    ], last_report_at: "2026-09-30 11:00:00" },
  ],
};

describe("UsageDurationPanel", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-30T02:00:00Z"));
    vi.clearAllMocks();
    vi.mocked(getUsageSummary).mockResolvedValue({ data: { code: 0, data: summary } } as never);
    vi.mocked(getUsageDevices).mockResolvedValue({ data: { code: 0, data: { total: 1, page: 1, page_size: 20, items: [
      { package_name: "com.a", device_id: "device-a", device_model: "Pixel", os: "14", duration_s: 270, sdk_version: "1.0", app_version: "2.0", last_report_at: "2026-09-30 10:00:00" },
    ] } } } as never);
    searchUsagePackages.mockResolvedValue({ data: { items: ["com.a", "com.b"] } });
  });

  it("uses the usage-backed package combobox and keeps the typed draft separate from applied scope", async () => {
    const wrapper = mount(UsageDurationPanel);
    const input = wrapper.get("[data-testid='usage-package-name']");
    await input.trigger("focus");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();

    expect(searchUsagePackages).toHaveBeenCalledWith("");
    expect(wrapper.find("[data-testid='usage-package-option']").exists()).toBe(true);
  });

  afterEach(() => vi.useRealTimers());

  it("loads the recent three Beijing days, keeps exact seconds, and shows all buckets", async () => {
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();

    expect(getUsageSummary).toHaveBeenCalledWith(summaryScope);
    expect((wrapper.get("[data-testid='usage-date-from']").element as HTMLInputElement).value).toBe("2026-09-28");
    expect((wrapper.get("[data-testid='usage-date-to']").element as HTMLInputElement).value).toBe("2026-09-30");
    expect(wrapper.get("[data-testid='usage-summary-row']").text()).toContain("1020 秒");
    expect(wrapper.get("[data-testid='usage-summary-row']").text()).toContain("17 分钟");
    expect(wrapper.get("[data-testid='usage-bucket-le_120']").text()).toContain("120 秒");
    expect(wrapper.get("[data-testid='usage-bucket-ge_1500']").text()).toContain("0");
  });

  it("loads one row's devices on expand, caches collapse/re-expand, and preserves applied scope", async () => {
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    await wrapper.get("[data-testid='usage-expand-0']").trigger("click");
    await flushPromises();

    expect(getUsageDevices).toHaveBeenCalledWith({ ...summaryScope, package_name: "com.a", page: 1, page_size: 10 });
    expect(wrapper.get("[data-testid='usage-device-row']").text()).toContain("device-a");
    expect(wrapper.get("[data-testid='usage-device-row']").text()).toContain("14");
    await wrapper.get("[data-testid='usage-expand-0']").trigger("click");
    await wrapper.get("[data-testid='usage-expand-0']").trigger("click");
    await flushPromises();
    expect(getUsageDevices).toHaveBeenCalledTimes(1);
  });

  it("paginates more than ten device details and resets pagination with the applied scope", async () => {
    vi.mocked(getUsageDevices).mockImplementation(async (scope) => ({
      data: {
        code: 0,
        data: {
          total: scope.page_size === 50 ? 75 : 25,
          page: scope.page,
          page_size: scope.page_size,
          items: Array.from({ length: Math.max(0, Math.min(scope.page_size ?? 10, (scope.page_size === 50 ? 75 : 25) - ((scope.page ?? 1) - 1) * (scope.page_size ?? 10))) }, (_, index) => ({
            package_name: "com.a",
            device_id: `device-${scope.page}-${index}`,
            device_model: "Pixel",
            os: "14",
            duration_s: 270,
            sdk_version: "1.0",
            app_version: "2.0",
            last_report_at: null,
          })),
        },
      },
    }) as never);
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    await wrapper.get("[data-testid='usage-expand-0']").trigger("click");
    await flushPromises();

    expect(wrapper.findAll("[data-testid='usage-device-row']")).toHaveLength(10);
    expect(wrapper.find("[data-testid='usage-device-next']").exists()).toBe(true);
    await wrapper.get("[data-testid='usage-device-next']").trigger("click");
    await flushPromises();
    expect(getUsageDevices).toHaveBeenLastCalledWith({ ...summaryScope, package_name: "com.a", page: 2, page_size: 10 });
    expect(wrapper.findAll("[data-testid='usage-device-row']")).toHaveLength(10);
    await wrapper.get("[data-testid='usage-device-next']").trigger("click");
    await flushPromises();
    expect(getUsageDevices).toHaveBeenLastCalledWith({ ...summaryScope, package_name: "com.a", page: 3, page_size: 10 });
    expect(wrapper.findAll("[data-testid='usage-device-row']")).toHaveLength(5);
    expect(wrapper.get("[data-testid='usage-device-prev']").element.hasAttribute("disabled")).toBe(false);

    await wrapper.get("[data-testid='usage-device-page-size']").setValue("50");
    await flushPromises();
    expect(getUsageDevices).toHaveBeenLastCalledWith({ ...summaryScope, package_name: "com.a", page: 1, page_size: 50 });
    expect(wrapper.findAll("[data-testid='usage-device-row']")).toHaveLength(50);
    expect(wrapper.get("[data-testid='usage-device-next']").element.hasAttribute("disabled")).toBe(false);
    await wrapper.get("[data-testid='usage-device-next']").trigger("click");
    await flushPromises();
    expect(getUsageDevices).toHaveBeenLastCalledWith({ ...summaryScope, package_name: "com.a", page: 2, page_size: 50 });
    expect(wrapper.findAll("[data-testid='usage-device-row']")).toHaveLength(25);
    expect(wrapper.get("[data-testid='usage-device-next']").element.hasAttribute("disabled")).toBe(true);
  });

  it("clears detail cache on scope query and prevents an old device response entering another row", async () => {
    let resolveA!: (value: unknown) => void;
    let resolveB!: (value: unknown) => void;
    vi.mocked(getUsageDevices)
      .mockReturnValueOnce(new Promise((resolve) => { resolveA = resolve; }) as never)
      .mockReturnValueOnce(new Promise((resolve) => { resolveB = resolve; }) as never);
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    await wrapper.get("[data-testid='usage-expand-0']").trigger("click");
    await wrapper.get("[data-testid='usage-expand-1']").trigger("click");
    resolveB({ data: { code: 0, data: { total: 1, page: 1, page_size: 20, items: [{ package_name: "com.b", device_id: "device-b", device_model: "iPhone", duration_s: 900, sdk_version: "2.0", app_version: "3.0", last_report_at: null }] } } });
    await flushPromises();
    resolveA({ data: { code: 0, data: { total: 1, page: 1, page_size: 20, items: [{ package_name: "com.a", device_id: "device-a", device_model: "Pixel", duration_s: 270, sdk_version: "1.0", app_version: "2.0", last_report_at: null }] } } });
    await flushPromises();
    expect(wrapper.get("[data-testid='usage-device-row']").text()).toContain("device-b");
    expect(wrapper.get("[data-testid='usage-device-row']").text()).not.toContain("device-a");

    await wrapper.get("[data-testid='usage-package-name']").setValue("com.next");
    await wrapper.get("[data-testid='usage-query']").trigger("click");
    await flushPromises();
    expect(wrapper.find("[data-testid='usage-device-row']").exists()).toBe(false);
    expect(getUsageSummary).toHaveBeenLastCalledWith({ ...summaryScope, package_name: "com.next" });
  });

  it("retries a failed device page without losing the applied scope", async () => {
    vi.mocked(getUsageDevices)
      .mockRejectedValueOnce(new Error("device timeout"))
      .mockResolvedValueOnce({ data: { code: 0, data: { total: 25, page: 1, page_size: 10, items: [{ package_name: "com.a", device_id: "retry-device", device_model: "Pixel", os: "14", duration_s: 120, sdk_version: "1.0", app_version: "2.0", last_report_at: null }] } } } as never);
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    await wrapper.get("[data-testid='usage-expand-0']").trigger("click");
    await flushPromises();
    expect(wrapper.get("[data-testid='usage-device-retry']").text()).toContain("重试");
    await wrapper.get("[data-testid='usage-device-retry']").trigger("click");
    await flushPromises();
    expect(getUsageDevices).toHaveBeenLastCalledWith({ ...summaryScope, package_name: "com.a", page: 1, page_size: 10 });
    expect(wrapper.get("[data-testid='usage-device-row']").text()).toContain("retry-device");
  });

  it("keeps only the newest summary scope when date/package queries resolve out of order", async () => {
    let resolveA!: (value: unknown) => void;
    let resolveB!: (value: unknown) => void;
    vi.mocked(getUsageSummary)
      .mockReturnValueOnce(new Promise((resolve) => { resolveA = resolve; }) as never)
      .mockReturnValueOnce(new Promise((resolve) => { resolveB = resolve; }) as never);
    const wrapper = mount(UsageDurationPanel);
    await wrapper.get("[data-testid='usage-package-name']").setValue("com.b");
    await wrapper.get("form").trigger("submit");
    resolveB({ data: { code: 0, data: { ...summary, items: [summary.items[1]] } } });
    await flushPromises();
    resolveA({ data: { code: 0, data: { ...summary, items: [summary.items[0]] } } });
    await flushPromises();
    expect(wrapper.get("[data-testid='usage-summary-row']").text()).toContain("com.b");
    expect(wrapper.get("[data-testid='usage-summary-row']").text()).not.toContain("com.a");
    wrapper.unmount();
  });

  it("shows summary request errors instead of an empty state", async () => {
    vi.mocked(getUsageSummary).mockRejectedValueOnce(new Error("usage unavailable"));
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    expect(wrapper.get("[data-testid='usage-error']").text()).toContain("usage unavailable");
    expect(wrapper.find("[data-testid='usage-empty']").exists()).toBe(false);
    wrapper.unmount();
  });

  it("keeps the last successful rows when an applied query fails", async () => {
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    vi.mocked(getUsageSummary).mockRejectedValueOnce(new Error("query unavailable"));
    await wrapper.get("[data-testid='usage-package-name']").setValue("com.failed");
    await wrapper.get("[data-testid='usage-query']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-testid='usage-error']").text()).toContain("query unavailable");
    expect(wrapper.get("[data-testid='usage-summary-row']").text()).toContain("com.a");
    expect(wrapper.get<HTMLInputElement>("[data-testid='usage-package-name']").element.value).toBe("com.failed");
    expect(wrapper.get("[data-testid='usage-applied-scope']").text()).toContain("全部包名");
    expect(wrapper.get("[data-testid='usage-applied-scope']").text()).toContain("2026-09-28");
    expect(wrapper.get("[data-testid='usage-applied-scope']").text()).not.toContain("com.failed");
  });

  it("keeps the last successful rows when refresh fails", async () => {
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    vi.mocked(getUsageSummary).mockRejectedValueOnce(new Error("refresh unavailable"));
    await wrapper.get("[data-testid='usage-refresh']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-testid='usage-error']").text()).toContain("refresh unavailable");
    expect(wrapper.get("[data-testid='usage-summary-row']").text()).toContain("com.a");
  });

  it("ignores an in-flight summary response after unmount", async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(getUsageSummary).mockReturnValueOnce(new Promise((nextResolve) => { resolve = nextResolve; }) as never);
    const wrapper = mount(UsageDurationPanel);
    wrapper.unmount();
    resolve({ data: { code: 0, data: summary } });
    await flushPromises();
    expect(wrapper.find("[data-testid='usage-summary-row']").exists()).toBe(false);
  });
});
