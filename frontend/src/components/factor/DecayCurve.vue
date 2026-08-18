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
  title: {
    text: props.halfLife != null ? `Half-life: ${props.halfLife}d` : 'IC Decay',
    textStyle: { color: '#999999', fontSize: 13 },
    left: 'center',
  },
  tooltip: {
    trigger: 'axis' as const,
    backgroundColor: '#fff',
    borderColor: '#EEEEEE',
    textStyle: { color: '#1A1A1A', fontSize: 12 },
  },
  grid: { top: 40, right: 20, bottom: 30, left: 50 },
  xAxis: {
    type: 'value' as const,
    name: 'Lag (days)',
    axisLabel: { color: '#999999', fontSize: 10 },
    nameTextStyle: { color: '#999999' },
    splitLine: { lineStyle: { color: '#F5F5F5' } },
  },
  yAxis: {
    type: 'value' as const,
    name: 'IC',
    axisLabel: { color: '#999999', fontSize: 10 },
    nameTextStyle: { color: '#999999' },
    splitLine: { lineStyle: { color: '#F5F5F5' } },
  },
  series: [{
    type: 'line' as const,
    data: props.data.map((d) => [+d.lag, +d.ic.toFixed(4)]),
    smooth: true,
    lineStyle: { color: '#FF6700', width: 2 },
    itemStyle: { color: '#FF6700' },
    areaStyle: {
      color: {
        type: 'linear',
        x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [
          { offset: 0, color: '#FF670030' },
          { offset: 1, color: '#FF670005' },
        ],
      },
    },
  }],
}))
</script>

<template>
  <VChart :option="option" autoresize class="w-full h-56" />
</template>
