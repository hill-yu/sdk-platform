import { beforeEach, describe, expect, it, vi } from "vitest";

const request = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/api/request", () => ({ default: request }));

import { createLogExport, downloadLogExport, searchLogPackages } from "@/api/logExports";

describe("log export api", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends package search and export filters", async () => {
    await searchLogPackages("tech");
    expect(request.get).toHaveBeenCalledWith("/log-packages", { params: { keyword: "tech", limit: 20 } });
    await createLogExport({ package_names: ["com.a"], log_level: "info" });
    expect(request.post).toHaveBeenCalledWith("/log-exports", { package_names: ["com.a"], log_level: "info" });
  });

  it("downloads csv as a blob", async () => {
    await downloadLogExport("job-id");
    expect(request.get).toHaveBeenCalledWith("/log-exports/job-id/download", { responseType: "blob", timeout: 60000 });
  });
});
