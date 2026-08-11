import { beforeEach, describe, expect, it, vi } from "vitest";

const { request } = vi.hoisted(() => ({
  request: { get: vi.fn() },
}));

vi.mock("@/api/request", () => ({ default: request }));

import { getEvents } from "@/api/dashboard";

describe("dashboard event API", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends the package_name event filter", () => {
    getEvents({ package_name: "com.example.app" });
    expect(request.get).toHaveBeenCalledWith("/events", {
      params: { package_name: "com.example.app" },
    });
  });
});
