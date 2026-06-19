<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import XmCard from '@/components/ui/XmCard.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import { usePortfolioStore } from '@/stores/usePortfolioStore'

use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const portfolioStore = usePortfolioStore()

// Simulated backtest data
const equityCurve = ref<number[]>([])
const benchmarkCurve = ref<number[]>([])
const yearlyReturns = ref([
  { year: '2021', ret: 0.28 },
  { year: '2022', ret: -0.12 },
  { year: '2023', ret: 0.35 },
  { year: '2024', ret: 0.22 },
  { year: '2025', ret: 0.08 },
])

function generateCurves() {
  let eq = 1000000
  let bm = 1000000
  equityCurve.value = [eq]
  benchmarkCurve.value = [bm]
  for (let i = 0; i < 252 * 4; i++) {
    eq *= 1 + (Math.random() - 0.48) * 0.02
    bm *= 1 + (Math.random() - 0.485) * 0.018
    equityCurve.value.push(parseFloat(eq.toFixed(0)))
    benchmarkCurve.value.push(parseFloat(bm.toFixed(0)))
  }
}
generateCurves()

const perfMetrics = computed(() => [
  { label: 'Total Return', value: `${((equityCurve.value[equityCurve.value.length-1] / 1000000 - 1) * 100).toFixed(1)}%`, isPositive: equityCurve.value[equityCurve.value.length-1] >= 1000000 },
  { label: 'Annual Return', value: '18.4%', isPositive: true },
  { label: 'Sharpe Ratio', value: '1.85', isPositive: true },
  { label: 'Max Drawdown', value: '-15.2%', isPositive: false },
  { label: 'Win Rate', value: '58.3%', isPositive: true },
  { label: 'Profit Factor', value: '2.14', isPositive: true },
])

const equityChartOption = computed(() => ({
  grid: { top: 12, right: 16, bottom: 4, left: 60 },
  tooltip: {
    trigger: 'axis' as const,
    backgroundColor: '#fff',
    borderColor: '#EEEEEE',
    textStyle: { color: '#1A1A1A', fontSize: 12 },
  },
  legend: {
    data: ['Strategy', 'Benchmark'],
    bottom: 0,
    textStyle: { fontSize: 11 },
  },
  xAxis: {
    type: 'category' as const,
    show: false,
    data: equityCurve.value.map((_, i) => i),
  },
  yAxis: {
    type: 'value' as const,
    splitLine: { lineStyle: { color: '#F5F5F5' } },
    axisLabel: { fontSize: 10, color: '#999999', formatter: (v: number) => `$${(v/1000).toFixed(0)}K` },
  },
  series: [
    {
      name: 'Strategy',
      type: 'line',
      data: equityCurve.value,
      smooth: true,
      symbol: 'none',
      lineStyle: { color: '#FF6700', width: 2 },
      areaStyle: { color: { type: 'linear', x:0,y:0,x2:0,y2:1, colorStops: [{offset:0,color:'#FF670020'},{offset:1,color:'#FF670002'}] }},
    },
    {
      name: 'Benchmark',
      type: 'line',
      data: benchmarkCurve.value,
      smooth: true,
      symbol: 'none',
      lineStyle: { color: '#999999', width: 1.5, type: 'dashed' },
    },
  ],
}))

const yearlyChartOption = computed(() => ({
  grid: { top: 8, right: 16, bottom: 4, left: 50 },
  tooltip: {
    trigger: 'axis' as const,
    backgroundColor: '#fff',
    borderColor: '#EEEEEE',
    textStyle: { color: '#1A1A1A', fontSize: 12 },
    valueFormatter: (v: number) => `${(v * 100).toFixed(1)}%`,
  },
  xAxis: {
    type: 'category' as const,
    data: yearlyReturns.value.map(y => y.year),
    axisLabel: { fontSize: 10, color: '#666666' },
  },
  yAxis: {
    type: 'value' as const,
    splitLine: { lineStyle: { color: '#F5F5F5' } },
    axisLabel: { fontSize: 10, color: '#999999', formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
  },
  series: [{
    type: 'bar',
    data: yearlyReturns.value.map(y => ({
      value: y.ret,
      itemStyle: { color: y.ret >= 0 ? '#16A34A' : '#DC2626', borderRadius: [4, 4, 0, 0] },
    })),
    barWidth: 28,
  }],
}))
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <!-- Performance Metrics -->
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      <XmCard v-for="m in perfMetrics" :key="m.label" class="!p-3">
        <div class="xm-metric-label text-xxs">{{ m.label }}</div>
        <div class="text-base font-mono font-bold mt-1" :class="m.isPositive ? 'xm-pnl-positive' : 'xm-pnl-negative'">
          {{ m.value }}
        </div>
      </XmCard>
    </div>

    <!-- Equity Curve -->
    <XmCard title="Backtest Equity Curve" subtitle="Strategy vs SPY Benchmark">
      <VChart :option="equityChartOption" style="height: 360px" autoresize />
    </XmCard>

    <!-- Yearly Returns -->
    <XmCard title="Annual Returns">
      <VChart :option="yearlyChartOption" style="height: 260px" autoresize />
    </XmCard>
  </div>
</template>
