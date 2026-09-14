import { beforeEach, describe, expect, it, vi } from "vitest";

const { request } = vi.hoisted(() => ({
  request: { get: vi.fn(), put: vi.fn(), post: vi.fn() },
}));

vi.mock("@/api/request", () => ({ default: request }));

import {
  getLogAnalysisDetail,
  getLogAnalysisDetails,
  getLogAnalysisSummary,
  getLogAnalysisColumns,
  getPackageProfile,
  postLogReparse,
  putLogAnalysisColumns,
  putPackageProfile,
} from "@/api/logAnalysis";
import type {
  LogDecodeItem,
  PackageProfilePayload,
  ReparseJob,
  ReparseJobStatus,
} from "@/api/logAnalysis";

const partialProfile = { alias: "Alias" } satisfies PackageProfilePayload;
const runningStatus: ReparseJobStatus = "running";
const runningJob: ReparseJob = {
  id: 1,
  package_name: null,
  range_start: "2026-08-01T00:00:00Z",
  range_end: "2026-08-08T00:00:00Z",
  cursor_event_id: null,
  cursor_server_ts: null,
  processed_count: 0,
  decoded_count: 0,
  failed_count: 0,
  status: runningStatus,
};
// @ts-expect-error LogDecodeItem.extra only accepts string or null.
const invalidExtra: LogDecodeItem["extra"] = 123;

void partialProfile;
void runningJob;
void invalidExtra;

describe("log analysis API", () => {
  beforeEach(() => vi.clearAllMocks());

  it("passes summary and details query parameters unchanged", () => {
    const summary = {
      date_from: "2026-08-01",
      date_to: "2026-08-07",
      package_name: "com.example.app",
      device_id: "device-1",
      log_level: "error" as const,
      page: 2,
      page_size: 50,
      sort_by: "success_rate",
      sort_order: "asc" as const,
    };
    const details = {
      date: "2026-08-07",
      package_name: "com.example.app",
      device_id: "device-1",
      log_level: "error" as const,
      status: "failed" as const,
      page: 3,
      page_size: 20,
    };

    getLogAnalysisSummary(summary);
    getLogAnalysisDetails(details);

    expect(request.get).toHaveBeenNthCalledWith(1, "/log-analysis/summary", { params: summary });
    expect(request.get).toHaveBeenNthCalledWith(2, "/log-analysis/details", { params: details });
  });

  it("passes composite detail keys and profile/column payloads unchanged", () => {
    const key = { event_server_ts: "2026-08-07T01:02:03Z", record_index: 1 };
    const profile = { alias: "Alias", company: "Company", account: "account-1" };
    const columns = { columns: ["date", "package_name", "alias"] };
    const reparse = { package_name: "com.example.app", status: "failed" as const };

    getLogAnalysisDetail(7, key);
    getPackageProfile("com.example.app");
    putPackageProfile("com.example.app", profile);
    getLogAnalysisColumns();
    putLogAnalysisColumns(columns);
    postLogReparse(reparse);

    expect(request.get).toHaveBeenNthCalledWith(1, "/log-analysis/details/7", { params: key });
    expect(request.get).toHaveBeenNthCalledWith(2, "/package-profiles", {
      params: { package_name: "com.example.app" },
    });
    expect(request.put).toHaveBeenNthCalledWith(1, "/package-profiles/com.example.app", profile);
    expect(request.get).toHaveBeenNthCalledWith(3, "/log-analysis/columns");
    expect(request.put).toHaveBeenNthCalledWith(2, "/log-analysis/columns", columns);
    expect(request.post).toHaveBeenCalledWith("/log-analysis/reparse", reparse);
  });
});
