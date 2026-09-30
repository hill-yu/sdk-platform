import { describe, expect, it, vi } from "vitest";

const { request } = vi.hoisted(() => ({ request: { get: vi.fn() } }));
vi.mock("@/api/request", () => ({ default: request }));

import { getUsageDevices, getUsageSummary } from "@/api/usageDurations";

describe("usage duration API", () => {
  it("passes the scope and expansion key unchanged", () => {
    const scope = { package_name: "com.example.app", date_from: "2026-09-28", hour_from: 0, date_to: "2026-09-30", hour_to: 23 };
    getUsageSummary(scope);
    getUsageDevices({ ...scope, device_model: "Pixel" });
    expect(request.get).toHaveBeenNthCalledWith(1, "/usage-durations/summary", { params: scope });
    expect(request.get).toHaveBeenNthCalledWith(2, "/usage-durations/devices", { params: { ...scope, device_model: "Pixel" } });
  });
});
