import { beforeEach, describe, expect, it, vi } from "vitest";

const { request } = vi.hoisted(() => ({ request: { get: vi.fn(), post: vi.fn() } }));
vi.mock("@/api/request", () => ({ default: request }));

import { getLatestParseJob, getMetricOverview, getParseJob, postParseJob } from "@/api/logMetrics";

describe("log metrics API", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps the complete UTC+8 scope on metrics and parse-job requests", () => {
    const scope = { package_name: "com.example.app", date_from: "2026-09-28", hour_from: 0, date_to: "2026-09-30", hour_to: 23 };
    getMetricOverview(scope);
    postParseJob(scope);
    getParseJob(7);
    getLatestParseJob(scope);

    expect(request.get).toHaveBeenNthCalledWith(1, "/log-analysis/metrics/overview", { params: scope });
    expect(request.post).toHaveBeenCalledWith("/log-analysis/parse-jobs", scope);
    expect(request.get).toHaveBeenNthCalledWith(2, "/log-analysis/parse-jobs/7");
    expect(request.get).toHaveBeenNthCalledWith(3, "/log-analysis/parse-jobs/latest", { params: scope });
  });
});
