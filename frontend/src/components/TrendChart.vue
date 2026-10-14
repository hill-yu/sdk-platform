<template>
  <VChart class="chart" :option="option" autoresize />
</template>

<script setup lang="ts">
import { computed } from "vue";
import { use } from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import { AriaComponent, GridComponent, LegendComponent, TooltipComponent, TitleComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import VChart from "vue-echarts";
import { buildTrendOption, type TrendOptionInput } from "@/components/trendOption";

use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, TitleComponent, AriaComponent, CanvasRenderer]);

const props = defineProps<TrendOptionInput>();
const option = computed(() => buildTrendOption(props));
</script>

<style scoped>
.chart { width: 100%; height: 340px; }
@media (prefers-reduced-motion: reduce) { .chart { scroll-behavior: auto; } }
</style>

