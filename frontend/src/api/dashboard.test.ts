import { beforeEach, describe, expect, it, vi } from "vitest";

const { request } = vi.hoisted(() => ({
  request: { get: vi.fn() },
}));

vi.mock("@/api/request", () => ({ default: request }));

import { getEventFilterOptions, getEvents } from "@/api/dashboard";
import type { EventQuery } from "@/api/dashboard";

describe("dashboard event API", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends all log filters to the event endpoint", () => {
    const params: EventQuery = {
      page: 2,
      page_size: 20,
      event_type: "log",
      package_name: "com.example.app",
      sdk_version: "1.4.0",
      device_id: "device-1",
      log_level: "error",
      date_from: "2026-08-01",
      date_to: "2026-08-13",
    };

    getEvents(params);
    expect(request.get).toHaveBeenCalledWith("/events", {
      params,
    });
  });

  it("loads filter options with an optional exact package name", () => {
    getEventFilterOptions("com.example.app");

    expect(request.get).toHaveBeenCalledWith("/events/filter-options", {
      params: { package_name: "com.example.app" },
    });
  });
});
