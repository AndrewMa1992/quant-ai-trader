<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([LineChart, TitleComponent, TooltipComponent, GridComponent, CanvasRenderer])

interface DecayPoint {
  lag: number
  ic: number
}

const props = defineProps<{ data: DecayPoint[]; halfLife?: number }>()

const option = computed(() => ({
  title: { text: props.halfLife != null ? `Half-life: ${props.halfLife}d` : 'IC Decay',
    textStyle: { color: '#8b92a8', fontSize: 13 }, left: 'center' },
  tooltip: { trigger: 'axis' as const },
  grid: { top: 40, right: 20, bottom: 30, left: 50 },
  xAxis: {
    type: 'value' as const, name: 'Lag (days)',
    axisLabel: { color: '#5c6378', fontSize: 10 },
    nameTextStyle: { color: '#8b92a8' },
  },
  yAxis: {
    type: 'value' as const, name: 'IC',
    axisLabel: { color: '#5c6378', fontSize: 10 },
    nameTextStyle: { color: '#8b92a8' },
    splitLine: { lineStyle: { color: '#1e293b' } },
  },
  series: [{
    type: 'line' as const,
    data: props.data.map((d) => [+d.lag, +d.ic.toFixed(4)]),
    smooth: true,
    lineStyle: { color: '#22c55e', width: 2 },
    itemStyle: { color: '#22c55e' },
    areaStyle: { color: 'rgba(34, 197, 94, 0.1)' },
    markLine: props.halfLife != null ? {
      silent: true,
      data: [{ xAxis: props.halfLife, label: { formatter: `HL: ${props.halfLife}d`, color: '#eab308' }, lineStyle: { color: '#eab308', type: 'dashed' as const } }],
    } : undefined,
  }],
}))
</script>

<template>
  <VChart v-if="data.length > 0" :option="option" style="height: 260px" autoresize />
  <p v-else class="text-text-muted text-sm text-center py-8">No decay data</p>
</template>
