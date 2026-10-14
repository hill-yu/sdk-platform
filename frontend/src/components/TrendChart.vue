<template>
  <VChart class="chart" :option="option" autoresize />
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { use } from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import { AriaComponent, GridComponent, LegendComponent, TooltipComponent, TitleComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import VChart from "vue-echarts";
import { buildTrendOption, type TrendOptionInput } from "@/components/trendOption";

use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, TitleComponent, AriaComponent, CanvasRenderer]);

const props = defineProps<TrendOptionInput>();
const prefersReducedMotion = ref(false);
let mediaQuery: MediaQueryList | undefined;

const updateMotionPreference = () => {
  prefersReducedMotion.value = mediaQuery?.matches ?? false;
};

onMounted(() => {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
  mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  updateMotionPreference();
  mediaQuery.addEventListener?.("change", updateMotionPreference);
});

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener?.("change", updateMotionPreference);
});

const option = computed(() => buildTrendOption(props, { reducedMotion: prefersReducedMotion.value }));
</script>

<style scoped>
.chart { width: 100%; height: 340px; }
@media (prefers-reduced-motion: reduce) { .chart { scroll-behavior: auto; } }
</style>

