<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { GaugeChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'

use([GaugeChart, CanvasRenderer])

interface Props {
  value: number
  max?: number
  label?: string
  colorStops?: Array<[number, string]>
  size?: number
}

const props = withDefaults(defineProps<Props>(), {
  max: 100,
  label: '',
  size: 140,
})

const defaultStops: Array<[number, string]> = [
  [0.3, '#22C55E'],
  [0.7, '#EAB308'],
  [1.0, '#EF4444'],
]

const option = computed(() => {
  const pct = Math.min((props.value / props.max) * 100, 100)
  const stops = props.colorStops || defaultStops
  return {
    series: [{
      type: 'gauge',
      startAngle: 210,
      endAngle: -30,
      center: ['50%', '55%'],
      radius: '85%',
      min: 0,
      max: 100,
      splitNumber: 5,
      axisLine: {
        show: true,
        lineStyle: {
          width: 12,
          color: stops.map(([p, c]) => [p, c]),
        },
      },
      pointer: {
        icon: 'path://M12.8,0.7l12,40.1H0.7L12.8,0.7z',
        length: '60%',
        width: 6,
        itemStyle: { color: '#1A1A1A' },
      },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      detail: {
        valueAnimation: true,
        formatter: '{value}%',
        fontSize: 18,
        fontWeight: 'bold',
        color: '#1A1A1A',
        offsetCenter: [0, '70%'],
      },
      title: props.label
        ? {
            offsetCenter: [0, '90%'],
            fontSize: 12,
            color: '#666666',
          }
        : { show: false },
      data: [{ value: Math.round(pct), name: props.label }],
    }],
  }
})
</script>

<template>
  <VChart :option="option" :style="{ height: size + 'px', width: size + 'px' }" autoresize />
</template>
