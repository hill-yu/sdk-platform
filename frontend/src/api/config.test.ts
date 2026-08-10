import { beforeEach, describe, expect, it, vi } from "vitest";

const { request } = vi.hoisted(() => ({
  request: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));

vi.mock("@/api/request", () => ({ default: request }));

import { getConfig, publishConfig, updateConfig } from "@/api/config";

describe("config API timeouts", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps ordinary reads on the default timeout", () => {
    getConfig(7);
    expect(request.get).toHaveBeenCalledWith("/configs/7");
  });

  it("allows 60 seconds for save and publish", () => {
    updateConfig(7, { config_data: {} });
    publishConfig(7);
    expect(request.put).toHaveBeenCalledWith("/configs/7", { config_data: {} }, { timeout: 60_000 });
    expect(request.post).toHaveBeenCalledWith("/configs/7/publish", undefined, { timeout: 60_000 });
  });
});
