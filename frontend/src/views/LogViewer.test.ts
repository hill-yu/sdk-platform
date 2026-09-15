import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EventItem } from "@/api/dashboard";

const {
  getEvents,
  getLogAnalysisColumns,
  getLogAnalysisSummary,
  getLogAnalysisDetails,
  getLogAnalysisDetail,
  putLogAnalysisColumns,
  putPackageProfile,
} = vi.hoisted(() => ({
  getEvents: vi.fn(),
  getLogAnalysisColumns: vi.fn(),
  getLogAnalysisSummary: vi.fn(),
  getLogAnalysisDetails: vi.fn(),
  getLogAnalysisDetail: vi.fn(),
  putLogAnalysisColumns: vi.fn(),
  putPackageProfile: vi.fn(),
}));
vi.mock("@/api/dashboard", async () => {
  const actual = await vi.importActual<typeof import("@/api/dashboard")>("@/api/dashboard");
  return { ...actual, getEvents };
});
vi.mock("@/api/logAnalysis", () => ({
  getLogAnalysisColumns,
  getLogAnalysisSummary,
  getLogAnalysisDetails,
  getLogAnalysisDetail,
  putLogAnalysisColumns,
  putPackageProfile,
}));

import LogViewer from "@/views/LogViewer.vue";

const fullExtra = "complete-extra-value-".repeat(30);

function makeItem(overrides: Partial<EventItem> = {}): EventItem {
  return {
    id: 1,
    event_type: "log",
    package_name: "com.example.app",
    device_id: "device-1",
    sdk_version: "1.2.3",
    payload: {
      level: "error",
      tag: "network",
      message: "request failed with timeout",
      extra: fullExtra,
    },
    client_ts: null,
    server_ts: "2026-08-13T10:00:00Z",
    ...overrides,
  };
}

function respond(items: EventItem[] = [makeItem()], total = items.length) {
  getEvents.mockResolvedValue({ data: { total, items } });
}

function respondAnalysis() {
  getLogAnalysisColumns.mockResolvedValue({
    data: {
      available_columns: ["date", "package_name", "alias", "user_count"],
      default_columns: ["date", "package_name", "alias", "user_count"],
      columns: ["date", "package_name", "alias", "user_count"],
    },
  });
  getLogAnalysisSummary.mockResolvedValue({
    data: {
      total: 1,
      page: 1,
      page_size: 20,
      items: [{ date: "2026-08-13", package_name: "com.example.app", alias: "示例", company: "公司", account: "account-1", primary_url: null, url_count: 0, user_count: 2, flow_count: 1, expected_click_count: 2, actual_click_count: 1, ad_click_count: 0, interstitial_presentation_count: 0, interstitial_click_count: 0, average_duration_ms: null, duration_sample_count: 0, success_rate: null, success_sample_count: 0, failed_count: 0, unsupported_count: 0, parse_failure_count: 0 }],
    },
  });
  getLogAnalysisDetails.mockResolvedValue({ data: { total: 0, page: 1, page_size: 20, items: [] } });
  getLogAnalysisDetail.mockResolvedValue({ data: {} });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function mountViewer() {
  const wrapper = mount(LogViewer);
  await flushPromises();
  await wrapper.get("[data-testid='raw-view-tab']").trigger("click");
  await flushPromises();
  return wrapper;
}

async function mountAnalysisViewer() {
  const wrapper = mount(LogViewer);
  await flushPromises();
  return wrapper;
}

describe("LogViewer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    respond();
    respondAnalysis();
  });

  afterEach(() => vi.restoreAllMocks());

  it("defaults to analysis view and starts summary and columns requests together", async () => {
    const summary = deferred<{ data: unknown }>();
    const columns = deferred<{ data: unknown }>();
    getLogAnalysisSummary.mockReturnValueOnce(summary.promise);
    getLogAnalysisColumns.mockReturnValueOnce(columns.promise);
    const wrapper = await mountAnalysisViewer();

    expect(wrapper.get("[data-testid='analysis-view-tab']").classes()).toContain("active");
    expect(wrapper.findAll("[data-testid='analysis-view']")).toHaveLength(1);
    expect(getLogAnalysisSummary).toHaveBeenCalledTimes(1);
    expect(getLogAnalysisColumns).toHaveBeenCalledTimes(1);
    expect(wrapper.findAll("[data-testid='log-list']")).toHaveLength(0);

    columns.resolve({ data: { available_columns: ["date", "package_name"], default_columns: ["date", "package_name"], columns: ["package_name", "date"] } });
    summary.resolve({ data: { total: 0, page: 1, page_size: 20, items: [] } });
    await flushPromises();
    expect(wrapper.findAll(".summary-table th").map((node) => node.text())).toEqual(["包名", "日期"]);
  });

  it("renders dynamic columns, null metrics, samples, and percentage values", async () => {
    getLogAnalysisColumns.mockResolvedValueOnce({ data: { available_columns: ["date", "package_name", "url", "average_duration_ms", "success_rate"], default_columns: ["date", "package_name"], columns: ["date", "package_name", "url", "average_duration_ms", "success_rate"] } });
    getLogAnalysisSummary.mockResolvedValueOnce({ data: { total: 1, page: 1, page_size: 20, items: [{ date: "2026-08-13", package_name: "com.example.app", alias: "", company: "", account: "", primary_url: "https://example.test", url_count: 1, user_count: 0, flow_count: 0, expected_click_count: 0, actual_click_count: 0, ad_click_count: 0, interstitial_presentation_count: 0, interstitial_click_count: 0, average_duration_ms: null, duration_sample_count: 0, success_rate: 0.5, success_sample_count: 2, failed_count: 0, unsupported_count: 0, parse_failure_count: 0 }] } });
    const wrapper = await mountAnalysisViewer();

    expect(wrapper.get("[data-testid='summary-row']").text()).toContain("https://example.test");
    expect(wrapper.get("[data-testid='summary-row']").text()).toContain("-（0 个样本）");
    expect(wrapper.get("[data-testid='summary-row']").text()).toContain("50%（2 个样本）");
  });

  it("loads details by date and package, then loads the full record by its composite key", async () => {
    const decoded = { event_id: 7, event_server_ts: "2026-08-13T10:00:00Z", record_index: 1, package_name: "com.example.app", device_id: "device-1", status: "success", decoder_version: "1.0.0", decoded_timestamp: null, url: null, config_id: null, window: null, expected_click_count: 2, actual_click_count: 1, ad_click_count: 0, interstitial_presentation_count: 0, interstitial_click_count: 0, interstitial_close_count: 0, duration_ms: 12, final_reason: "done", is_success: true, decoded_payload: { ok: true }, parse_error: null, parsed_at: null, extra: "original-extra" };
    getLogAnalysisDetails.mockResolvedValueOnce({ data: { total: 1, page: 1, page_size: 20, items: [decoded] } });
    getLogAnalysisDetail.mockResolvedValueOnce({ data: decoded });
    const wrapper = await mountAnalysisViewer();

    await wrapper.get("[data-testid='summary-row']").trigger("click");
    await flushPromises();
    expect(getLogAnalysisDetails).toHaveBeenCalledWith(expect.objectContaining({ date: "2026-08-13", package_name: "com.example.app", page: 1, page_size: 20 }));
    await wrapper.get("[data-testid='analysis-detail-row']").trigger("click");
    await flushPromises();
    expect(getLogAnalysisDetail).toHaveBeenCalledWith(7, { event_server_ts: "2026-08-13T10:00:00Z", record_index: 1 });
    expect(wrapper.get("[data-testid='raw-extra']").text()).toBe("original-extra");
  });

  it("keeps the previous summary and synchronizes a saved profile across same-package rows", async () => {
    getLogAnalysisSummary.mockResolvedValueOnce({ data: { total: 2, page: 1, page_size: 20, items: [{ date: "2026-08-12", package_name: "com.example.app", alias: "", company: "", account: "", primary_url: null, url_count: 0, user_count: 1, flow_count: 0, expected_click_count: 0, actual_click_count: 0, ad_click_count: 0, interstitial_presentation_count: 0, interstitial_click_count: 0, average_duration_ms: null, duration_sample_count: 0, success_rate: null, success_sample_count: 0, failed_count: 0, unsupported_count: 0, parse_failure_count: 0 }, { date: "2026-08-13", package_name: "com.example.app", alias: "", company: "", account: "", primary_url: null, url_count: 0, user_count: 1, flow_count: 0, expected_click_count: 0, actual_click_count: 0, ad_click_count: 0, interstitial_presentation_count: 0, interstitial_click_count: 0, average_duration_ms: null, duration_sample_count: 0, success_rate: null, success_sample_count: 0, failed_count: 0, unsupported_count: 0, parse_failure_count: 0 }] } });
    putPackageProfile.mockResolvedValueOnce({ data: { package_name: "com.example.app", alias: "Shared", company: "", account: "" } });
    const wrapper = await mountAnalysisViewer();
    const cells = wrapper.findAll("[data-testid='profile-edit']");
    await cells[0].trigger("click");
    await wrapper.get("[data-testid='profile-input']").setValue("Shared");
    await wrapper.get("[data-testid='profile-save']").trigger("click");
    await flushPromises();

    expect(wrapper.findAll("[data-testid='profile-value']").map((node) => node.text())).toEqual(["Shared", "Shared"]);
  });

  it("keeps summary rows when a later analysis query fails", async () => {
    const wrapper = await mountAnalysisViewer();
    getLogAnalysisSummary.mockRejectedValueOnce(new Error("summary unavailable"));
    await wrapper.get("[data-testid='filter-refresh']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-testid='summary-row']").text()).toContain("com.example.app");
    expect(wrapper.get("[data-testid='error-feedback']").text()).toContain("summary unavailable");
  });

  it("saves column drafts globally only after the save request succeeds", async () => {
    getLogAnalysisColumns.mockResolvedValueOnce({ data: { available_columns: ["date", "package_name", "alias", "user_count"], default_columns: ["date", "package_name"], columns: ["date", "package_name", "alias"] } });
    putLogAnalysisColumns.mockResolvedValueOnce({ data: { available_columns: ["date", "package_name", "alias", "user_count"], default_columns: ["date", "package_name"], columns: ["date", "package_name", "user_count"] } });
    const wrapper = await mountAnalysisViewer();
    await wrapper.get("[data-testid='configure-columns']").trigger("click");
    await wrapper.get("[data-testid='column-add-user_count']").trigger("click");
    await wrapper.get("[data-testid='column-settings-save']").trigger("click");

    expect(putLogAnalysisColumns).toHaveBeenCalledWith({ columns: ["date", "package_name", "alias", "user_count"] });
    await flushPromises();
    expect(wrapper.findAll("[data-testid='column-settings-modal']")).toHaveLength(0);
    expect(wrapper.findAll(".summary-table th").map((node) => node.text())).toEqual(["日期", "包名", "用户数"]);
  });

  it("loads only log events and sends all selected filters", async () => {
    const wrapper = await mountViewer();
    expect(getEvents).toHaveBeenLastCalledWith(expect.objectContaining({
      page: 1,
      page_size: 20,
      event_type: "log",
    }));

    await wrapper.get("[data-testid='package-filter']").setValue("com.filtered.app");
    await wrapper.get("[data-testid='device-filter']").setValue("device-9");
    await wrapper.get("[data-testid='level-filter']").setValue("error");
    await wrapper.get("[data-testid='date-from-filter']").setValue("2026-08-01");
    await wrapper.get("[data-testid='date-to-filter']").setValue("2026-08-13");
    await wrapper.get("[data-testid='query-button']").trigger("click");
    await flushPromises();

    expect(getEvents).toHaveBeenLastCalledWith({
      page: 1,
      page_size: 20,
      event_type: "log",
      package_name: "com.filtered.app",
      device_id: "device-9",
      log_level: "error",
      date_from: "2026-08-01",
      date_to: "2026-08-13",
    });
  });

  it("resets the page only for a new query and refresh preserves filters and page", async () => {
    respond([makeItem()], 41);
    const wrapper = await mountViewer();
    await wrapper.get("[data-testid='package-filter']").setValue("com.keep.app");
    await wrapper.get("[data-testid='next-page']").trigger("click");
    await flushPromises();
    expect(getEvents).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, package_name: "com.keep.app" }));

    await wrapper.get("[data-testid='refresh-button']").trigger("click");
    await flushPromises();
    expect(getEvents).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, package_name: "com.keep.app" }));

    await wrapper.get("[data-testid='query-button']").trigger("click");
    await flushPromises();
    expect(getEvents).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, package_name: "com.keep.app" }));
  });

  it("shows a selected log in the detail panel without expanding extra in the list", async () => {
    const wrapper = await mountViewer();
    expect(wrapper.get("[data-testid='log-tag']").text()).toBe("network");
    expect(wrapper.get("[data-testid='log-message']").text()).toContain("request failed");
    expect(wrapper.get("[data-testid='level-tag']").classes()).toContain("level-error");
    expect(wrapper.get("[data-testid='log-list']").text()).not.toContain(fullExtra);

    await wrapper.get("[data-testid='log-row']").trigger("click");
    expect(wrapper.get("[data-testid='log-extra']").text()).toBe(fullExtra);
  });

  it("keeps valid results when a later query fails", async () => {
    const wrapper = await mountViewer();
    expect(wrapper.get("[data-testid='log-row']").text()).toContain("com.example.app");
    getEvents.mockRejectedValueOnce(new Error("query unavailable"));

    await wrapper.get("[data-testid='refresh-button']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-testid='error-feedback']").text()).toContain("query unavailable");
    expect(wrapper.get("[data-testid='log-row']").text()).toContain("com.example.app");
  });

  it("ignores an older response that finishes after a newer query", async () => {
    const wrapper = await mountViewer();
    const older = deferred<{ data: { total: number; items: EventItem[] } }>();
    const newer = deferred<{ data: { total: number; items: EventItem[] } }>();
    getEvents.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);

    await wrapper.get("[data-testid='refresh-button']").trigger("click");
    await wrapper.get("[data-testid='query-button']").trigger("click");
    newer.resolve({ data: { total: 1, items: [makeItem({ package_name: "new.result" })] } });
    await flushPromises();
    older.resolve({ data: { total: 1, items: [makeItem({ package_name: "old.result" })] } });
    await flushPromises();

    expect(wrapper.get("[data-testid='log-row']").text()).toContain("new.result");
    expect(wrapper.get("[data-testid='log-row']").text()).not.toContain("old.result");
  });

  it("rebinds selected details to the refreshed item with the same id", async () => {
    const wrapper = await mountViewer();
    await wrapper.get("[data-testid='log-row']").trigger("click");
    respond([makeItem({ payload: { message: "updated message", extra: "updated extra" } })]);

    await wrapper.get("[data-testid='refresh-button']").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-testid='log-extra']").text()).toBe("updated extra");
    expect(wrapper.text()).toContain("updated message");
  });

  it("restores the previous page when pagination fails", async () => {
    respond([makeItem()], 41);
    const wrapper = await mountViewer();
    getEvents.mockRejectedValueOnce(new Error("page unavailable"));

    await wrapper.get("[data-testid='next-page']").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("第 1 / 3 页");
    expect(wrapper.get("[data-testid='log-row']").text()).toContain("com.example.app");
  });

  it("keeps the last successful page when rapid pagination resolves out of order and the latest request fails", async () => {
    respond([makeItem({ package_name: "page.one" })], 61);
    const wrapper = await mountViewer();
    const pageTwo = deferred<{ data: { total: number; items: EventItem[] } }>();
    const pageThree = deferred<{ data: { total: number; items: EventItem[] } }>();
    getEvents.mockReturnValueOnce(pageTwo.promise).mockReturnValueOnce(pageThree.promise);

    await wrapper.get("[data-testid='next-page']").trigger("click");
    await wrapper.get("[data-testid='next-page']").trigger("click");
    expect(getEvents).toHaveBeenNthCalledWith(2, expect.objectContaining({ page: 2 }));
    expect(getEvents).toHaveBeenNthCalledWith(3, expect.objectContaining({ page: 3 }));

    pageTwo.resolve({ data: { total: 61, items: [makeItem({ package_name: "page.two" })] } });
    await flushPromises();
    pageThree.reject(new Error("page three unavailable"));
    await flushPromises();

    expect(wrapper.text()).toContain("第 1 / 4 页");
    expect(wrapper.get("[data-testid='log-row']").text()).toContain("page.one");
  });

  it("keeps the last successful page when consecutive pagination requests fail", async () => {
    respond([makeItem({ package_name: "page.one" })], 61);
    const wrapper = await mountViewer();
    const pageTwo = deferred<{ data: { total: number; items: EventItem[] } }>();
    const pageThree = deferred<{ data: { total: number; items: EventItem[] } }>();
    getEvents.mockReturnValueOnce(pageTwo.promise).mockReturnValueOnce(pageThree.promise);

    await wrapper.get("[data-testid='next-page']").trigger("click");
    await wrapper.get("[data-testid='next-page']").trigger("click");
    pageTwo.reject(new Error("page two unavailable"));
    await flushPromises();
    pageThree.reject(new Error("page three unavailable"));
    await flushPromises();

    expect(wrapper.text()).toContain("第 1 / 4 页");
    expect(wrapper.get("[data-testid='log-row']").text()).toContain("page.one");
    expect(wrapper.get("[data-testid='error-feedback']").text()).toContain("page three unavailable");
  });

  it("never requests beyond the last page during rapid next-page clicks", async () => {
    respond([makeItem()], 61);
    const wrapper = await mountViewer();
    getEvents.mockImplementation(() => new Promise(() => {}));

    for (let index = 0; index < 8; index += 1) {
      await wrapper.get("[data-testid='next-page']").trigger("click");
    }

    const requestedPages = getEvents.mock.calls.slice(1).map(([query]) => query.page);
    expect(requestedPages).toEqual([2, 3, 4]);
    expect(wrapper.get("[data-testid='next-page']").attributes("disabled")).toBeDefined();
  });

  it("never requests below the first page during rapid previous-page clicks", async () => {
    respond([makeItem()], 61);
    const wrapper = await mountViewer();
    getEvents.mockResolvedValueOnce({ data: { total: 61, items: [makeItem()] } });
    await wrapper.get("[data-testid='next-page']").trigger("click");
    await flushPromises();
    getEvents.mockImplementation(() => new Promise(() => {}));

    for (let index = 0; index < 8; index += 1) {
      await wrapper.get("[data-testid='previous-page']").trigger("click");
    }

    const requestedPages = getEvents.mock.calls.slice(2).map(([query]) => query.page);
    expect(requestedPages).toEqual([1]);
    expect(wrapper.get("[data-testid='previous-page']").attributes("disabled")).toBeDefined();
  });

  it("updates feedback after copy success and failure", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("copy denied")) },
    });
    const wrapper = await mountViewer();
    await wrapper.get("[data-testid='log-row']").trigger("click");

    await wrapper.get("[data-testid='copy-extra']").trigger("click");
    await flushPromises();
    expect(wrapper.get("[data-testid='success-feedback']").text()).toContain("复制成功");

    await wrapper.get("[data-testid='copy-extra']").trigger("click");
    await flushPromises();
    expect(wrapper.get("[data-testid='error-feedback']").text()).toContain("copy denied");
  });

  it("renders null fields as dashes and displays the empty result state", async () => {
    respond([makeItem({ device_id: null, sdk_version: null, payload: { level: null, tag: null, message: null, extra: null } })]);
    const wrapper = await mountViewer();
    expect(wrapper.get("[data-testid='log-row']").text()).toContain("-");

    respond([]);
    await wrapper.get("[data-testid='refresh-button']").trigger("click");
    await flushPromises();
    expect(wrapper.get("[data-testid='empty-state']").text()).toContain("没有日志");
  });

  it("disables previous on the first page and next on the last page", async () => {
    respond([makeItem()], 21);
    const wrapper = await mountViewer();
    expect(wrapper.get("[data-testid='previous-page']").attributes("disabled")).toBeDefined();
    expect(wrapper.get("[data-testid='next-page']").attributes("disabled")).toBeUndefined();

    await wrapper.get("[data-testid='next-page']").trigger("click");
    await flushPromises();
    expect(wrapper.get("[data-testid='next-page']").attributes("disabled")).toBeDefined();
  });
});
