<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([BarChart, TitleComponent, TooltipComponent, GridComponent, CanvasRenderer])

interface Slice {
  label: string
  completed: number
  total: number
  status: 'pending' | 'executing' | 'filled'
}

const props = defineProps<{ slices: Slice[] }>()

const option = computed(() => ({
  title: { text: 'Order Slice Progress', textStyle: { color: '#8b92a8', fontSize: 13 }, left: 'center' },
  tooltip: { trigger: 'axis' as const },
  grid: { top: 35, right: 20, bottom: 30, left: 50 },
  xAxis: {
    type: 'category' as const,
    data: props.slices.map((s) => s.label),
    axisLabel: { color: '#5c6378', fontSize: 10 },
  },
  yAxis: { type: 'value' as const, axisLabel: { color: '#5c6378', fontSize: 10 }, splitLine: { lineStyle: { color: '#1e293b' } } },
  series: [
    {
      type: 'bar' as const,
      data: props.slices.map((s) => s.total),
      itemStyle: { color: '#1e293b', borderRadius: [4, 4, 0, 0] },
      barGap: '-100%',
    },
    {
      type: 'bar' as const,
      data: props.slices.map((s) => +(s.completed / Math.max(s.total, 1) * 100).toFixed(1)),
      itemStyle: {
        color: (params: { dataIndex: number }) => {
          const st = props.slices[params.dataIndex]?.status
          return st === 'filled' ? '#22c55e' : st === 'executing' ? '#eab308' : '#3b82f6'
        },
        borderRadius: [4, 4, 0, 0],
      },
    },
  ],
}))
</script>

<template>
  <VChart v-if="slices.length > 0" :option="option" style="height: 220px" autoresize />
  <p v-else class="text-text-muted text-sm text-center py-8">No active orders</p>
</template>
