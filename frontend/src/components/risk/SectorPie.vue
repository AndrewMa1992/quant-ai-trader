<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([PieChart, TitleComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{ data: Record<string, number> }>()

const pieData = computed(() =>
  Object.entries(props.data).map(([name, value]) => ({ name, value: +value.toFixed(4) })),
)

const option = computed(() => ({
  title: { text: 'Sector Concentration', textStyle: { color: '#8b92a8', fontSize: 13 }, left: 'center' },
  tooltip: { trigger: 'item' as const },
  legend: { bottom: 0, textStyle: { color: '#8b92a8', fontSize: 10 } },
  series: [{
    type: 'pie' as const,
    radius: ['40%', '72%'],
    center: ['50%', '48%'],
    data: pieData.value,
    label: { color: '#8b92a8', fontSize: 10, formatter: '{b}\n{d}%' },
    itemStyle: { borderColor: '#0b0e17', borderWidth: 2 },
    color: ['#3b82f6', '#22d3ee', '#22c55e', '#eab308', '#a855f7', '#ef4444', '#f97316', '#ec4899'],
  }],
}))
</script>

<template>
  <VChart v-if="pieData.length > 0" :option="option" style="height: 280px" autoresize />
  <p v-else class="text-text-muted text-sm text-center py-8">No sector data</p>
</template>
