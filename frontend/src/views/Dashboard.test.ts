import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getBreakdown: vi.fn(),
  getEvents: vi.fn(),
  getSummary: vi.fn(),
  getTrend: vi.fn(),
}));
vi.mock("@/api/dashboard", () => api);

import Dashboard from "@/views/Dashboard.vue";

const event = (id: number) => ({ id, event_type: id % 2 ? "click" : "log", device_id: `device-${id}`, server_ts: "2026-10-14T06:00:00Z", payload: { page: "/home", element: "open_button", raw: id } });

describe("Dashboard home interactions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getSummary.mockResolvedValue({ data: { today_pv: 28416, yesterday_pv: 25200, today_uv: 3284, yesterday_uv: 3392, today_events: 46872, yesterday_events: 41600, active_devices: 2916, yesterday_active_devices: 3000 } });
    api.getTrend.mockResolvedValue({ data: { points: [{ time: "00:00", count: 100, uv: 20 }] } });
    api.getBreakdown.mockResolvedValue({ data: [{ name: "log", count: 72 }, { name: "click", count: 28 }] });
    api.getEvents.mockResolvedValue({ data: { total: 16, items: Array.from({ length: 8 }, (_, index) => event(index + 1)) } });
  });

  it("renders four metrics and keeps trend, distribution, filter, pagination, and expansion semantics", async () => {
    const wrapper = mount(Dashboard, { global: { stubs: { TrendChart: true } } });
    await flushPromises();

    expect(wrapper.text()).toContain("今日 PV");
    expect(wrapper.text()).toContain("今日 UV");
    expect(wrapper.text()).toContain("今日事件数");
    expect(wrapper.text()).toContain("活跃设备");
    expect(api.getTrend).toHaveBeenCalledWith({ range: "24h", event_type: undefined });
    expect(api.getBreakdown).toHaveBeenCalledWith({ dimension: "event_type" });
    expect(api.getEvents).toHaveBeenCalledWith(expect.objectContaining({ page: 1, page_size: 8 }));

    await wrapper.findAll("select")[0].setValue("7d");
    await wrapper.findAll("select")[1].setValue("click");
    await wrapper.findAll("select")[2].setValue("page");
    await wrapper.findAll("select")[3].setValue("click");
    await wrapper.get("input[placeholder='package_name']").setValue("com.example.reader");
    await wrapper.findAll("input[type='date']")[0].setValue("2026-10-14");
    await wrapper.findAll("input[type='date']")[1].setValue("2026-10-14");
    await wrapper.findAll("button").find((button) => button.text() === "筛选")!.trigger("click");
    await wrapper.get("tbody tr.clickable-row").trigger("click");
    expect(wrapper.find(".expanded-row").exists()).toBe(true);
    expect(wrapper.text()).toContain('"raw": 1');
    await wrapper.get(".pager button:last-child").trigger("click");
    await flushPromises();

    expect(api.getTrend).toHaveBeenLastCalledWith({ range: "7d", event_type: "click" });
    expect(api.getBreakdown).toHaveBeenLastCalledWith({ dimension: "page" });
    expect(api.getEvents).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, page_size: 8, event_type: "click", package_name: "com.example.reader", date_from: "2026-10-14", date_to: "2026-10-14" }));
  });

  it("preserves loading, error, and empty states", async () => {
    let resolveSummary!: (value: unknown) => void;
    api.getSummary.mockReturnValueOnce(new Promise((resolve) => { resolveSummary = resolve; }));
    const loadingWrapper = mount(Dashboard, { global: { stubs: { TrendChart: true } } });
    await nextTick();
    expect(loadingWrapper.text()).toContain("正在加载数据");
    resolveSummary({ data: {} });
    await flushPromises();

    api.getSummary.mockRejectedValueOnce(new Error("summary unavailable"));
    const errorWrapper = mount(Dashboard, { global: { stubs: { TrendChart: true } } });
    await flushPromises();
    expect(errorWrapper.text()).toContain("summary unavailable");

    api.getEvents.mockResolvedValueOnce({ data: { total: 0, items: [] } });
    const emptyWrapper = mount(Dashboard, { global: { stubs: { TrendChart: true } } });
    await flushPromises();
    expect(emptyWrapper.text()).toContain("当前筛选条件下没有事件数据");
  });
});
