<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([RadarChart, TitleComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{ exposures: Record<string, number> }>()

const labels = computed(() => Object.keys(props.exposures))
const values = computed(() => Object.values(props.exposures))

const option = computed(() => ({
  title: { text: 'Barra Factor Exposure', textStyle: { color: '#8b92a8', fontSize: 13 }, left: 'center' },
  tooltip: {},
  legend: { show: false },
  radar: {
    indicator: labels.value.map((l) => ({ name: l, max: Math.max(...values.value.map(Math.abs)) * 1.5 || 1 })),
    axisName: { color: '#8b92a8', fontSize: 10 },
    splitArea: { areaStyle: { color: ['transparent'] } },
    splitLine: { lineStyle: { color: '#1e293b' } },
    axisLine: { lineStyle: { color: '#1e293b' } },
  },
  series: [{
    type: 'radar' as const,
    data: [{ value: values.value, name: 'Exposure', areaStyle: { color: 'rgba(34, 211, 238, 0.15)' }, lineStyle: { color: '#22d3ee', width: 2 }, itemStyle: { color: '#22d3ee' } }],
  }],
}))
</script>

<template>
  <VChart v-if="labels.length > 0" :option="option" style="height: 320px" autoresize />
  <p v-else class="text-text-muted text-sm text-center py-8">No Barra data</p>
</template>
