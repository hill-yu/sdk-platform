import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { cancelParseJob, getParseJob, postParseJob } from "@/api/logMetrics";
import LogParseTaskPanel from "@/components/LogParseTaskPanel.vue";

vi.mock("@/api/logMetrics", () => ({
  cancelParseJob: vi.fn(),
  getParseJob: vi.fn(),
  postParseJob: vi.fn(),
}));

const scope = {
  package_name: "com.example.app",
  date_from: "2026-09-28",
  hour_from: 0,
  date_to: "2026-09-30",
  hour_to: 23,
};

const job = (status: "pending" | "running" | "success" | "cancelled" | "failed") => ({
  id: 11,
  ...scope,
  range_start: "2026-09-28T00:00:00+08:00",
  range_end: "2026-09-30T23:59:59+08:00",
  status,
  total_count: 10,
  processed_count: status === "success" ? 10 : 2,
  h1_count: 4,
  failed_h1_count: 0,
  no_h1_count: 0,
});

describe("LogParseTaskPanel", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(postParseJob).mockResolvedValue({ data: { code: 0, data: job("pending") } } as never);
    vi.mocked(getParseJob).mockResolvedValue({ data: { code: 0, data: job("success") } } as never);
    vi.mocked(cancelParseJob).mockResolvedValue({ data: { code: 0, data: job("cancelled") } } as never);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("starts one parse job, polls until terminal, and emits refresh on completion", async () => {
    const wrapper = mount(LogParseTaskPanel, { props: { scope } });

    await wrapper.get("[data-testid='start-parse']").trigger("click");
    expect(postParseJob).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(getParseJob).toHaveBeenCalledWith(11);
    expect(wrapper.emitted("refresh")).toHaveLength(1);
    expect(getParseJob).toHaveBeenCalledTimes(1);
  });

  it("cancels the active job and clears polling on unmount", async () => {
    vi.mocked(getParseJob).mockResolvedValue({ data: { code: 0, data: job("running") } } as never);
    const wrapper = mount(LogParseTaskPanel, { props: { scope } });

    await wrapper.get("[data-testid='start-parse']").trigger("click");
    await wrapper.get("[data-testid='cancel-parse']").trigger("click");
    expect(cancelParseJob).toHaveBeenCalledWith(11);
    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(5000);
    expect(getParseJob).not.toHaveBeenCalled();
  });
});
