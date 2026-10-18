import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getHistoricalParseJobs = vi.hoisted(() => vi.fn());
vi.mock("@/api/logMetrics", () => ({ getHistoricalParseJobs }));
import LogHistoryPanel from "@/components/LogHistoryPanel.vue";

describe("LogHistoryPanel", () => {
  beforeEach(() => getHistoricalParseJobs.mockReset().mockResolvedValue({ data: { code: 0, data: { total: 2, page: 1, page_size: 10, items: [
    { id: 2, package_name: "com.example.app", status: "success", historical_available: true, range_start: "2026-10-01", range_end: "2026-10-02" },
    { id: 1, package_name: "com.example.app", status: "failed", historical_available: false, range_start: "2026-09-01", range_end: "2026-09-02", error_summary: "解析失败" },
  ] } } }));

  it("loads the effective package history and only opens successful jobs", async () => {
    const wrapper = mount(LogHistoryPanel, { props: { packageName: "com.example.app" } });
    await flushPromises();
    expect(getHistoricalParseJobs).toHaveBeenCalledWith({ package_name: "com.example.app", page: 1, page_size: 10 });
    expect(wrapper.findAll("[data-testid='history-job']")).toHaveLength(2);
    await wrapper.findAll("[data-testid='history-job']")[0].trigger("click");
    expect(wrapper.emitted("select")?.[0]?.[0]).toMatchObject({ id: 2 });
    expect(wrapper.findAll("[data-testid='history-job']")[1].attributes("disabled")).toBeDefined();
  });

  it("does not let an older package response replace the current list", async () => {
    let resolveOld!: (value: unknown) => void;
    const old = new Promise((resolve) => { resolveOld = resolve; });
    getHistoricalParseJobs.mockReset().mockReturnValueOnce(old).mockResolvedValueOnce({ data: { code: 0, data: { items: [{ id: 9, package_name: "new", status: "success", historical_available: true }] } } });
    const wrapper = mount(LogHistoryPanel, { props: { packageName: "old" } });
    await wrapper.setProps({ packageName: "new" });
    await flushPromises();
    resolveOld({ data: { code: 0, data: { items: [{ id: 8, package_name: "old", status: "success", historical_available: true }] } } });
    await flushPromises();
    expect(wrapper.text()).toContain("#9");
    expect(wrapper.text()).not.toContain("#8");
  });
});
