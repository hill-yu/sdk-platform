import { describe, expect, it } from "vitest";
import { flattenConfig, rowsToConfig } from "./configTable";

describe("config table conversion", () => {
  it("round trips nested values and arrays", () => {
    const source = { mainConfig: { enabled: true, count: 2, rules: ["a", "b"], empty: null } };
    expect(rowsToConfig(flattenConfig(source))).toEqual(source);
  });

  it("rejects duplicate and parent-child paths", () => {
    expect(() => rowsToConfig([
      { path: "mainConfig", type: "object", value: "{}" },
      { path: "mainConfig.enabled", type: "boolean", value: "true" },
    ])).toThrow("父子冲突");
  });

  it("refuses unsupported key syntax without changing the JSON", () => {
    expect(() => flattenConfig({ "a.b": 1 })).toThrow("继续使用 JSON 模式");
  });
});
