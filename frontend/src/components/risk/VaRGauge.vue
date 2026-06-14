<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { GaugeChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'

use([GaugeChart, CanvasRenderer])

const props = defineProps<{ value: number; title?: string }>()

const pct = computed(() => +(props.value * 100).toFixed(2))

const option = computed(() => ({
  title: { text: props.title ?? 'VaR', textStyle: { color: '#8b92a8', fontSize: 13 }, left: 'center', bottom: 0 },
  series: [{
    type: 'gauge' as const,
    startAngle: 210,
    endAngle: -30,
    min: 0,
    max: Math.max(pct.value * 2, 10),
    center: ['50%', '50%'],
    radius: '85%',
    progress: { show: true, width: 10, roundCap: true, itemStyle: { color: '#ef4444' } },
    axisLine: { lineStyle: { width: 10, color: [[1, '#1e293b']] } },
    axisTick: { show: false },
    splitLine: { show: false },
    axisLabel: { show: false },
    detail: {
      valueAnimation: true,
      formatter: '{value}%',
      color: '#e4e8f1',
      fontSize: 18,
      offsetCenter: [0, '60%'],
    },
    data: [{ value: pct.value, name: 'VaR' }],
  }],
}))
</script>

<template>
  <VChart :option="option" style="height: 220px" autoresize />
</template>
