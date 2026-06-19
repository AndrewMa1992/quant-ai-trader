<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([BarChart, TitleComponent, TooltipComponent, GridComponent, CanvasRenderer])

interface ICRecord {
  date: string
  ic: number
}

const props = defineProps<{ data: ICRecord[]; title?: string }>()

const option = computed(() => ({
  title: { text: props.title ?? 'IC Rank', textStyle: { color: '#8b92a8', fontSize: 13 }, left: 'center' },
  tooltip: { trigger: 'axis' as const },
  grid: { top: 35, right: 20, bottom: 30, left: 50 },
  xAxis: {
    type: 'category' as const,
    data: props.data.map((d) => d.date.slice(0, 10)),
    axisLabel: { color: '#5c6378', fontSize: 10 },
  },
  yAxis: {
    type: 'value' as const,
    axisLabel: { color: '#5c6378', fontSize: 10 },
    splitLine: { lineStyle: { color: '#1e293b' } },
  },
  series: [{
    type: 'bar' as const,
    data: props.data.map((d) => +d.ic.toFixed(4)),
    itemStyle: {
      color: (params: { value: number }) => params.value >= 0 ? '#22c55e' : '#ef4444',
    },
  }],
}))
</script>

<template>
  <VChart :option="option" style="height: 280px" autoresize />
</template>
