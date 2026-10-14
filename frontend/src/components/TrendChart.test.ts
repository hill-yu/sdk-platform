import { describe, expect, it } from "vitest";
import { buildTrendOption } from "@/components/trendOption";

describe("TrendChart themes", () => {
  it("keeps the default dark bar plus line chart", () => {
    const option = buildTrendOption({ title: "趋势", labels: ["00:00"], counts: [10], uv: [2] });

    expect(option.series.map((series) => series.type)).toEqual(["bar", "line"]);
    expect(option.yAxis).toHaveLength(2);
  });

  it("uses light line plus line with explicit dual-axis labels and reduced motion", () => {
    const option = buildTrendOption({ title: "趋势", labels: ["00:00"], counts: [10], uv: [2], light: true });

    expect(option.series.map((series) => series.type)).toEqual(["line", "line"]);
    expect(option.yAxis.map((axis) => axis.name)).toEqual(["事件数", "UV"]);
    expect(option.animation).toBe(true);
    expect(option.animationDuration).toBe(240);
    expect(option.aria).toBeDefined();
  });
});
