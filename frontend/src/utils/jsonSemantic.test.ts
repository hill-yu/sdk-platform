import { describe, expect, it } from "vitest";
import { jsonSemanticallyEqual } from "@/utils/jsonSemantic";

describe("jsonSemanticallyEqual", () => {
  it("ignores object key order but preserves array order", () => {
    expect(jsonSemanticallyEqual({ a: 1, b: { c: 2 } }, { b: { c: 2 }, a: 1 })).toBe(true);
    expect(jsonSemanticallyEqual({ items: [1, 2] }, { items: [2, 1] })).toBe(false);
  });

  it("distinguishes types, values, and missing keys", () => {
    expect(jsonSemanticallyEqual({ value: 1 }, { value: "1" })).toBe(false);
    expect(jsonSemanticallyEqual({ value: null }, {})).toBe(false);
    expect(jsonSemanticallyEqual({ value: "" }, { value: false })).toBe(false);
  });
});
