import { describe, expect, it } from "vitest";

import { defaultRecentThreeDays } from "@/utils/logDateRange";

describe("defaultRecentThreeDays", () => {
  it("uses Beijing calendar dates without converting through UTC strings", () => {
    expect(defaultRecentThreeDays(new Date("2026-09-29T16:30:00Z"))).toEqual({
      date_from: "2026-09-28",
      hour_from: 0,
      date_to: "2026-09-30",
      hour_to: 23,
    });
  });
});
