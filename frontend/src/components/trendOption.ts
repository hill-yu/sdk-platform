export type TrendOptionInput = { title: string; labels: string[]; counts: number[]; uv?: number[]; pie?: boolean; light?: boolean };
export type TrendOptionConfig = { reducedMotion?: boolean };

export function buildTrendOption(input: TrendOptionInput, config: TrendOptionConfig = {}) {
  const light = true;
  const reducedMotion = config.reducedMotion === true;
  const textColor = "#334155";
  const mutedColor = "#64748b";
  const gridColor = "#e5e7eb";
  const countColor = "#2563eb";
  const uvColor = "#14b8a6";
  const piePalette = ["#2563eb", "#14b8a6", "#60a5fa", "#2dd4bf", "#1d4ed8", "#0f766e"];

  if (input.pie) {
    return {
      color: piePalette,
      title: { text: input.title, textStyle: { color: textColor } },
      tooltip: { trigger: "item" },
      legend: { bottom: 8, textStyle: { color: mutedColor } },
      series: [{ type: "pie", radius: ["40%", "72%"], data: input.labels.map((name, index) => ({ name, value: input.counts[index] ?? 0, itemStyle: { color: piePalette[index % piePalette.length] } })) }],
    };
  }

  return {
    animation: !reducedMotion,
    ...(reducedMotion ? {} : { animationDuration: 240, animationDurationUpdate: 180 }),
    aria: { enabled: true, decal: { show: false } },
    title: { text: input.title, textStyle: { color: textColor } },
    tooltip: { trigger: "axis" },
    legend: { textStyle: { color: mutedColor } },
    grid: { left: 44, right: 42, top: 56, bottom: 28, containLabel: true },
    xAxis: { type: "category", data: input.labels, axisLabel: { color: mutedColor }, axisLine: { lineStyle: { color: gridColor } } },
    yAxis: [
      { type: "value", name: "事件数", nameTextStyle: { color: mutedColor }, axisLabel: { color: mutedColor }, splitLine: { lineStyle: { color: gridColor } } },
      { type: "value", name: "UV", nameTextStyle: { color: mutedColor }, axisLabel: { color: mutedColor }, splitLine: { show: false } },
    ],
    series: [
      { name: "事件数", type: "line", data: input.counts, itemStyle: { color: countColor }, lineStyle: { color: countColor, width: 2 }, symbol: "circle" },
      { name: "UV", type: "line", yAxisIndex: 1, smooth: true, data: input.uv ?? [], itemStyle: { color: uvColor }, lineStyle: { color: uvColor, width: 2 } },
    ],
  };
}

