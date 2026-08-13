import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EventItem } from "@/api/dashboard";
import LogDetail from "@/components/LogDetail.vue";

const longExtra = "raw-extra-".repeat(80);

function makeItem(overrides: Partial<EventItem> = {}): EventItem {
  return {
    id: 7,
    event_type: "log",
    package_name: "com.example.app",
    device_id: null,
    sdk_version: null,
    payload: {
      level: null,
      tag: null,
      message: null,
      extra: longExtra,
    },
    client_ts: null,
    server_ts: "2026-08-13T10:00:00Z",
    ...overrides,
  };
}

function mockClipboard(writeText: ReturnType<typeof vi.fn>) {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
}

describe("LogDetail", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows null fields as dashes and renders the complete extra value", () => {
    const wrapper = mount(LogDetail, { props: { item: makeItem() } });

    expect(wrapper.findAll(".detail-value").map((node) => node.text())).toContain("-");
    expect(wrapper.get("[data-testid='log-extra']").text()).toBe(longExtra);
  });

  it("copies extra and emits copy-success", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    mockClipboard(writeText);
    const wrapper = mount(LogDetail, { props: { item: makeItem() } });

    await wrapper.get("[data-testid='copy-extra']").trigger("click");
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith(longExtra));
    expect(wrapper.emitted("copy-success")).toHaveLength(1);
  });

  it("copies an empty string for null extra and emits copy-error when copying fails", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("clipboard denied"));
    mockClipboard(writeText);
    const wrapper = mount(LogDetail, {
      props: { item: makeItem({ payload: { extra: null } }) },
    });

    expect(wrapper.get("[data-testid='log-extra']").text()).toBe("-");
    await wrapper.get("[data-testid='copy-extra']").trigger("click");
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith(""));
    expect(wrapper.emitted("copy-error")).toEqual([["clipboard denied"]]);
  });
});
