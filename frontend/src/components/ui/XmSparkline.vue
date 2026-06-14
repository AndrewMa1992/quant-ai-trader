<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([LineChart, GridComponent, CanvasRenderer])

interface Props {
  data: number[]
  color?: string
  height?: number
  showArea?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  color: '#FF6700',
  height: 40,
  showArea: false,
})

const option = computed(() => ({
  grid: { top: 2, right: 0, bottom: 2, left: 0 },
  xAxis: { type: 'category' as const, show: false, data: props.data.map((_, i) => i) },
  yAxis: { type: 'value' as const, show: false, min: 'dataMin', max: 'dataMax' },
  series: [{
    type: 'line',
    data: props.data,
    smooth: true,
    symbol: 'none',
    lineStyle: { color: props.color, width: 1.5 },
    areaStyle: props.showArea
      ? {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: props.color + '30' },
              { offset: 1, color: props.color + '05' },
            ],
          },
        }
      : undefined,
  }],
}))
</script>

<template>
  <VChart :option="option" :style="{ height: height + 'px', width: '100%' }" autoresize />
</template>
