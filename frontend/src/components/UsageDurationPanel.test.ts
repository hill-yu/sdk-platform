import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getUsageDevices, getUsageSummary } from "@/api/usageDurations";
import UsageDurationPanel from "@/components/UsageDurationPanel.vue";

vi.mock("@/api/usageDurations", () => ({
  getUsageDevices: vi.fn(),
  getUsageSummary: vi.fn(),
}));

const summaryScope = { date_from: "2026-09-28", hour_from: 0, date_to: "2026-09-30", hour_to: 23 };
const summary = {
  total: 2,
  page: 1,
  page_size: 20,
  items: [
    { package_name: "com.a", device_model: "Pixel", device_count: 2, total_duration_s: 540, average_duration_s: 270, buckets: [
      { key: "le_300", count: 1, share: 0.5 }, { key: "301_600", count: 1, share: 0.5 }, { key: "601_899", count: 0, share: 0 }, { key: "ge_900", count: 0, share: 0 },
    ], last_report_at: "2026-09-30 10:00:00" },
    { package_name: "com.b", device_model: "iPhone", device_count: 1, total_duration_s: 900, average_duration_s: 900, buckets: [
      { key: "le_300", count: 0, share: 0 }, { key: "301_600", count: 0, share: 0 }, { key: "601_899", count: 0, share: 0 }, { key: "ge_900", count: 1, share: 1 },
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
      { package_name: "com.a", device_id: "device-a", device_model: "Pixel", duration_s: 270, sdk_version: "1.0", app_version: "2.0", last_report_at: "2026-09-30 10:00:00" },
    ] } } } as never);
  });

  afterEach(() => vi.useRealTimers());

  it("loads the recent three Beijing days, keeps exact seconds, and shows all buckets", async () => {
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();

    expect(getUsageSummary).toHaveBeenCalledWith(summaryScope);
    expect((wrapper.get("[data-testid='usage-date-from']").element as HTMLInputElement).value).toBe("2026-09-28");
    expect((wrapper.get("[data-testid='usage-date-to']").element as HTMLInputElement).value).toBe("2026-09-30");
    expect(wrapper.get("[data-testid='usage-summary-row']").text()).toContain("540 秒");
    expect(wrapper.get("[data-testid='usage-summary-row']").text()).toContain("9 分钟");
    expect(wrapper.get("[data-testid='usage-bucket-le_300']").text()).toContain("1");
    expect(wrapper.get("[data-testid='usage-bucket-ge_900']").text()).toContain("0");
  });

  it("loads one row's devices on expand, caches collapse/re-expand, and preserves applied scope", async () => {
    const wrapper = mount(UsageDurationPanel);
    await flushPromises();
    await wrapper.get("[data-testid='usage-expand-0']").trigger("click");
    await flushPromises();

    expect(getUsageDevices).toHaveBeenCalledWith({ ...summaryScope, package_name: "com.a", device_model: "Pixel", page: 1, page_size: 20 });
    expect(wrapper.get("[data-testid='usage-device-row']").text()).toContain("device-a");
    await wrapper.get("[data-testid='usage-expand-0']").trigger("click");
    await wrapper.get("[data-testid='usage-expand-0']").trigger("click");
    await flushPromises();
    expect(getUsageDevices).toHaveBeenCalledTimes(1);
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
});
