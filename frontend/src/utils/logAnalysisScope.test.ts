import { describe, expect, it } from "vitest";

import { analysisScopeUtcRange, defaultAnalysisScope, validateAnalysisScope } from "@/utils/logAnalysisScope";

describe("logAnalysisScope", () => {
  it("defaults to the latest three Beijing calendar days", () => {
    expect(defaultAnalysisScope(new Date("2026-10-08T00:30:00Z"))).toEqual({
      package_name: "",
      date_from: "2026-10-06",
      hour_from: 0,
      date_to: "2026-10-08",
      hour_to: 23,
    });
  });

  it("accepts seven calendar days and rejects the eighth", () => {
    const valid = {
      package_name: "com.example.app",
      date_from: "2026-10-01",
      hour_from: 0,
      date_to: "2026-10-07",
      hour_to: 23,
    };
    expect(validateAnalysisScope(valid)).toBeNull();
    expect(validateAnalysisScope({ ...valid, date_to: "2026-10-08" })).toContain("7");
  });

  it("converts the Beijing hour scope to an exact UTC half-open range", () => {
    expect(analysisScopeUtcRange({ package_name: "com.example.app", date_from: "2026-10-01", hour_from: 8, date_to: "2026-10-01", hour_to: 17 })).toEqual({
      range_start_utc: "2026-10-01T00:00:00.000Z",
      range_end_utc: "2026-10-01T10:00:00.000Z",
    });
  });
});
