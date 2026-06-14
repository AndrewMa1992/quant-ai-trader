<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([BarChart, TitleComponent, TooltipComponent, GridComponent, CanvasRenderer])

interface Item {
  feature: string
  importance: number
}

const props = defineProps<{ data: Item[] }>()

const sorted = computed(() => [...props.data].sort((a, b) => b.importance - a.importance))

const option = computed(() => ({
  title: { text: 'Feature Importance', textStyle: { color: '#8b92a8', fontSize: 13 }, left: 'center' },
  tooltip: { trigger: 'axis' as const },
  grid: { top: 35, right: 20, bottom: 10, left: 120 },
  xAxis: { type: 'value' as const, axisLabel: { color: '#5c6378', fontSize: 10 }, splitLine: { lineStyle: { color: '#1e293b' } } },
  yAxis: {
    type: 'category' as const,
    data: sorted.value.map((d) => d.feature),
    axisLabel: { color: '#8b92a8', fontSize: 10 },
    inverse: true,
  },
  series: [{
    type: 'bar' as const,
    data: sorted.value.map((d) => +d.importance.toFixed(4)),
    itemStyle: {
      borderRadius: [0, 4, 4, 0],
      color: '#a855f7',
    },
  }],
}))
</script>

<template>
  <VChart v-if="data.length > 0" :option="option" style="height: 280px" autoresize />
  <p v-else class="text-text-muted text-sm text-center py-8">No importance data</p>
</template>
