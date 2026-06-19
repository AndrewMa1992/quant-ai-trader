<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { ScatterChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([ScatterChart, TitleComponent, TooltipComponent, GridComponent, CanvasRenderer])

interface Point {
  predicted: number
  actual: number
}

const props = defineProps<{ data: Point[] }>()

const option = computed(() => {
  const all = [...props.data.map((d) => d.predicted), ...props.data.map((d) => d.actual)]
  const mm = Math.max(Math.abs(Math.max(...all)), Math.abs(Math.min(...all))) || 1

  return {
    title: { text: 'Predicted vs Actual', textStyle: { color: '#8b92a8', fontSize: 13 }, left: 'center' },
    tooltip: { trigger: 'item' as const, formatter: (p: { value: [number, number] }) =>
      `Pred: ${p.value[0].toFixed(4)}<br/>Actual: ${p.value[1].toFixed(4)}` },
    grid: { top: 40, right: 20, bottom: 30, left: 50 },
    xAxis: { name: 'Predicted', type: 'value' as const, min: -mm, max: mm, axisLabel: { color: '#5c6378', fontSize: 10 }, nameTextStyle: { color: '#8b92a8' }, splitLine: { lineStyle: { color: '#1e293b' } } },
    yAxis: { name: 'Actual', type: 'value' as const, min: -mm, max: mm, axisLabel: { color: '#5c6378', fontSize: 10 }, nameTextStyle: { color: '#8b92a8' }, splitLine: { lineStyle: { color: '#1e293b' } } },
    series: [
      { type: 'scatter' as const, data: props.data.map((d) => [+d.predicted.toFixed(4), +d.actual.toFixed(4)]), symbolSize: 5, itemStyle: { color: '#3b82f6' } },
      { type: 'line' as const, data: [[-mm, -mm], [mm, mm]], symbol: 'none' as const, lineStyle: { color: '#22c55e', type: 'dashed' as const, width: 1 } },
    ],
  }
})
</script>

<template>
  <VChart v-if="data.length > 0" :option="option" style="height: 300px" autoresize />
  <p v-else class="text-text-muted text-sm text-center py-8">No prediction data</p>
</template>
