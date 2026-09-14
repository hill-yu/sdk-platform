import { describe, expect, it } from "vitest";

import { formatBusinessTime } from "@/utils/dateTime";

describe("formatBusinessTime", () => {
  it("formats a timezone-aware ISO timestamp as UTC+8 business time", () => {
    expect(formatBusinessTime("2026-08-17T01:30:00Z")).toBe("2026-08-17 09:30:00");
    expect(formatBusinessTime("2026-08-17T01:30:00+00:00")).toBe("2026-08-17 09:30:00");
  });

  it("returns a dash for null, invalid, or timezone-less values", () => {
    expect(formatBusinessTime(null)).toBe("-");
    expect(formatBusinessTime("not-a-date")).toBe("-");
    expect(formatBusinessTime("2026-08-17T01:30:00")).toBe("-");
  });
});
