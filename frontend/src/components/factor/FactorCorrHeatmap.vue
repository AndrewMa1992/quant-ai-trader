<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { HeatmapChart } from 'echarts/charts'
import { TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([HeatmapChart, TooltipComponent, VisualMapComponent, CanvasRenderer])

const props = defineProps<{ matrix: Record<string, Record<string, number>> }>()

const factors = computed(() => Object.keys(props.matrix))

const heatmapData = computed(() => {
  const data: [number, number, number][] = []
  factors.value.forEach((row, ri) => {
    Object.entries(props.matrix[row] ?? {}).forEach(([col, val]) => {
      const ci = factors.value.indexOf(col)
      if (ci >= 0) data.push([ci, ri, +val.toFixed(3)])
    })
  })
  return data
})

const option = computed(() => ({
  tooltip: { formatter: (p: { data: [number, number, number] }) =>
    `${factors.value[p.data[1]]} × ${factors.value[p.data[0]]}: ${p.data[2].toFixed(3)}` },
  grid: { left: 120, right: 40, top: 20, bottom: 100 },
  xAxis: {
    type: 'category' as const,
    data: factors.value,
    axisLabel: { color: '#8b92a8', fontSize: 10, rotate: 45 },
  },
  yAxis: {
    type: 'category' as const,
    data: factors.value,
    axisLabel: { color: '#8b92a8', fontSize: 10 },
  },
  visualMap: {
    min: -1, max: 1,
    inRange: { color: ['#ef4444', '#111827', '#22c55e'] },
    show: false,
  },
  series: [{
    type: 'heatmap' as const,
    data: heatmapData.value,
    label: { show: heatmapData.value.length <= 25, fontSize: 9, color: '#e4e8f1' },
  }],
}))
</script>

<template>
  <VChart v-if="factors.length > 0" :option="option" style="height: 340px" autoresize />
  <p v-else class="text-text-muted text-sm text-center py-8">No correlation data</p>
</template>
