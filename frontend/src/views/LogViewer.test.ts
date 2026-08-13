import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EventItem } from "@/api/dashboard";

const { getEvents } = vi.hoisted(() => ({ getEvents: vi.fn() }));
vi.mock("@/api/dashboard", async () => {
  const actual = await vi.importActual<typeof import("@/api/dashboard")>("@/api/dashboard");
  return { ...actual, getEvents };
});

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
  return wrapper;
}

describe("LogViewer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    respond();
  });

  afterEach(() => vi.restoreAllMocks());

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
