<template>
  <VChart class="chart" :option="option" autoresize />
</template>

<script setup lang="ts">
import { computed } from "vue";
import { use } from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  TitleComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import VChart from "vue-echarts";

use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, TitleComponent, CanvasRenderer]);

const props = defineProps<{
  title: string;
  labels: string[];
  counts: number[];
  uv?: number[];
  pie?: boolean;
}>();

const option = computed(() => {
  if (props.pie) {
    return {
      title: { text: props.title, textStyle: { color: "#f3efe8" } },
      tooltip: { trigger: "item" },
      legend: { textStyle: { color: "#c7c2b6" } },
      series: [
        {
          type: "pie",
          radius: ["40%", "72%"],
          data: props.labels.map((name, index) => ({ name, value: props.counts[index] ?? 0 })),
        },
      ],
    };
  }

  return {
    title: { text: props.title, textStyle: { color: "#f3efe8" } },
    tooltip: { trigger: "axis" },
    legend: { textStyle: { color: "#b8b0a1" } },
    grid: { left: 36, right: 24, top: 56, bottom: 24, containLabel: true },
    xAxis: {
      type: "category",
      data: props.labels,
      axisLabel: { color: "#c7c2b6" },
    },
    yAxis: [
      { type: "value", axisLabel: { color: "#c7c2b6" } },
      { type: "value", axisLabel: { color: "#c7c2b6" } },
    ],
    series: [
      {
        name: "事件数",
        type: "bar",
        data: props.counts,
        itemStyle: { color: "#d68c45" },
      },
      {
        name: "UV",
        type: "line",
        yAxisIndex: 1,
        smooth: true,
        data: props.uv ?? [],
        itemStyle: { color: "#67a47d" },
      },
    ],
  };
});
</script>

<style scoped>
.chart {
  width: 100%;
  height: 340px;
}
</style>
