import { describe, expect, it } from "vitest";
import { buildTrendOption } from "@/components/trendOption";

describe("TrendChart themes", () => {
  it("keeps the default dark bar plus line chart", () => {
    const option = buildTrendOption({ title: "趋势", labels: ["00:00"], counts: [10], uv: [2] }) as any;

    expect(option.series.map((series: { type: string }) => series.type)).toEqual(["bar", "line"]);
    expect(option.yAxis).toHaveLength(2);
  });

  it("uses light line plus line with explicit dual-axis labels and reduced motion", () => {
    const option = buildTrendOption({ title: "趋势", labels: ["00:00"], counts: [10], uv: [2], light: true }, { reducedMotion: true }) as any;

    expect(option.series.map((series: { type: string }) => series.type)).toEqual(["line", "line"]);
    expect((option.yAxis as Array<{ name?: string }>).map((axis) => axis.name)).toEqual(["事件数", "UV"]);
    expect(option.animation).toBe(false);
    expect(option.animationDuration).toBeUndefined();
    expect(option.aria).toBeDefined();
  });

  it("uses a stable blue and teal palette for light pie charts", () => {
    const option = buildTrendOption({ title: "分布", labels: ["点击", "日志", "其他"], counts: [10, 6, 3], pie: true, light: true }) as any;

    expect(option.color).toEqual(["#2563eb", "#14b8a6", "#60a5fa", "#2dd4bf", "#1d4ed8", "#0f766e"]);
    expect(option.series[0].data.map((item: { itemStyle?: { color?: string } }) => item.itemStyle?.color)).toEqual(["#2563eb", "#14b8a6", "#60a5fa"]);
  });
});
