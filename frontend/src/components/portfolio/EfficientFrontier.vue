<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { ScatterChart, LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([ScatterChart, LineChart, TitleComponent, TooltipComponent, GridComponent, CanvasRenderer])

interface FrontierPoint {
  risk: number
  return_: number
  type: string
}

const props = defineProps<{ points: FrontierPoint[]; current?: { risk: number; return_: number } }>()

const frontier = computed(() => props.points.filter((p) => p.type === 'frontier'))
const individual = computed(() => props.points.filter((p) => p.type !== 'frontier'))

const option = computed(() => {
  const allRisks = props.points.map((p) => p.risk)
  const allRets = props.points.map((p) => p.return_)
  const rxMin = Math.max(0, Math.min(...allRisks) * 0.9)
  const rxMax = Math.max(...allRisks) * 1.1
  const ryMin = Math.min(...allRets) * 0.9
  const ryMax = Math.max(...allRets) * 1.1

  const series: unknown[] = [
    {
      type: 'line' as const, name: 'Efficient Frontier',
      data: frontier.value.map((p) => [+p.risk.toFixed(4), +p.return_.toFixed(4)]),
      smooth: true, lineStyle: { color: '#22c55e', width: 2 },
      symbol: 'none' as const, z: 1,
    },
    {
      type: 'scatter' as const, name: 'Assets',
      data: individual.value.map((p) => [+p.risk.toFixed(4), +p.return_.toFixed(4)]),
      symbolSize: 8, itemStyle: { color: '#3b82f6' }, z: 2,
    },
  ]

  if (props.current) {
    series.push({
      type: 'scatter' as const, name: 'Current Portfolio',
      data: [[props.current.risk, props.current.return_]],
      symbolSize: 16, itemStyle: { color: '#22d3ee', borderColor: '#fff', borderWidth: 2 }, z: 3,
    })
  }

  return {
    title: { text: 'Efficient Frontier', textStyle: { color: '#8b92a8', fontSize: 13 }, left: 'center' },
    tooltip: { trigger: 'item' as const },
    legend: { data: ['Efficient Frontier', 'Assets', 'Current Portfolio'], bottom: 0, textStyle: { color: '#8b92a8', fontSize: 10 } },
    grid: { top: 35, right: 20, bottom: 40, left: 60 },
    xAxis: { name: 'Risk (σ)', type: 'value' as const, min: rxMin, max: rxMax, axisLabel: { color: '#5c6378', fontSize: 10 }, nameTextStyle: { color: '#8b92a8' }, splitLine: { lineStyle: { color: '#1e293b' } } },
    yAxis: { name: 'Return (μ)', type: 'value' as const, min: ryMin, max: ryMax, axisLabel: { color: '#5c6378', fontSize: 10 }, nameTextStyle: { color: '#8b92a8' }, splitLine: { lineStyle: { color: '#1e293b' } } },
    series,
  }
})
</script>

<template>
  <VChart v-if="points.length > 0" :option="option" style="height: 340px" autoresize />
  <p v-else class="text-text-muted text-sm text-center py-8">No frontier data</p>
</template>
