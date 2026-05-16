<template>
  <div class="signal-trend-chart" :style="{ width, height }">
    <div :ref="(el) => chartRef = el" style="width: 100%; height: 100%;"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, onUnmounted } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  ticker: String,
  history: {
    type: Array,
    default: () => [],
  },
  width: {
    type: String,
    default: '100%',
  },
  height: {
    type: String,
    default: '80px',
  },
})

const chartRef = ref(null)
let chart = null

function getColor(decision) {
  if (decision === 'buy') return '#22c55e'
  if (decision === 'sell') return '#ef4444'
  return '#6b7280'
}

function renderChart() {
  if (!chartRef.value || !props.history.length) return

  if (!chart) {
    chart = echarts.init(chartRef.value, null, { renderer: 'canvas' })
  }

  const data = props.history
  const cycles = data.map((d) => d.cycle || 0)
  const strengths = data.map((d) => d.strength || 0)
  const decisions = data.map((d) => d.decision || 'hold')

  const lineColor = '#8b5cf6'
  const areaColor = 'rgba(139, 92, 246, 0.1)'

  // 标记 decision 变化点
  const markPoints = []
  for (let i = 1; i < decisions.length; i++) {
    if (decisions[i] !== decisions[i - 1]) {
      markPoints.push({
        coord: [i, strengths[i]],
        symbol: 'pin',
        symbolSize: 24,
        itemStyle: { color: getColor(decisions[i]) },
        label: {
          show: false,
        },
      })
    }
  }

  chart.setOption({
    backgroundColor: 'transparent',
    grid: {
      left: 0,
      right: 0,
      top: 6,
      bottom: 4,
    },
    xAxis: {
      type: 'category',
      data: cycles,
      show: false,
    },
    yAxis: {
      type: 'value',
      min: -1,
      max: 1,
      show: false,
      splitLine: { show: false },
    },
    series: [
      {
        type: 'line',
        data: strengths,
        smooth: true,
        showSymbol: false,
        lineStyle: {
          color: lineColor,
          width: 2,
        },
        areaStyle: {
          color: areaColor,
        },
        markPoint: {
          data: markPoints,
          symbol: 'circle',
          symbolSize: 6,
          itemStyle: {
            color: lineColor,
          },
        },
      },
    ],
    animation: true,
    animationDuration: 300,
  })
}

watch(
  () => props.history,
  () => renderChart(),
  { deep: true }
)

onMounted(() => {
  renderChart()
  window.addEventListener('resize', () => chart?.resize())
})

onUnmounted(() => {
  window.removeEventListener('resize', () => chart?.resize())
  chart?.dispose()
})
</script>

<style scoped>
.signal-trend-chart {
  display: flex;
  align-items: center;
}
</style>
