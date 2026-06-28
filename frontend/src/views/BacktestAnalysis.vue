<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import XmCard from '@/components/ui/XmCard.vue'
import { usePortfolioStore } from '@/stores/usePortfolioStore'
import { analysisApi, type PortfolioHistoryPoint, type YearlyReturn } from '@/api/executionApi'

use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const portfolioStore = usePortfolioStore()

// ── Reactive state ──
const historyData = ref<PortfolioHistoryPoint[]>([])
const yearlyReturnData = ref<YearlyReturn[]>([])
const loading = ref(false)
const hasData = computed(() => !loading.value && historyData.value.length > 0)

// ── Fetch real data ──
onMounted(async () => {
  loading.value = true
  try {
    const [history, yearly] = await Promise.all([
      analysisApi.getPortfolioHistory(),
      analysisApi.getYearlyReturns(),
    ])
    historyData.value = history ?? []
    yearlyReturnData.value = yearly ?? []
  } catch {
    // Silent degrade — leave data empty for empty-state UI
  } finally {
    loading.value = false
  }
})

// ── Derived equity curves from NAV history ──
const equityCurve = computed<number[]>(() => historyData.value.map((p) => p.nav))
const benchmarkCurve = computed<number[]>(() => historyData.value.map((p) => p.benchmark))

// ── Compute performance metrics from portfolio history ──
interface PerfMetric {
  label: string
  value: string
  isPositive: boolean
}

/** Daily returns from the NAV curve. */
function dailyReturns(navs: number[]): number[] {
  const rets: number[] = []
  for (let i = 1; i < navs.length; i++) {
    if (navs[i - 1] > 0) {
      rets.push(navs[i] / navs[i - 1] - 1)
    }
  }
  return rets
}

/** Maximum drawdown from NAV peak. */
function maxDrawdown(navs: number[]): number {
  let peak = navs[0] ?? 0
  let mdd = 0
  for (const n of navs) {
    if (n > peak) peak = n
    const dd = peak > 0 ? (n - peak) / peak : 0
    if (dd < mdd) mdd = dd
  }
  return mdd
}

const perfMetrics = computed<PerfMetric[]>(() => {
  const navs = equityCurve.value
  if (navs.length < 2) {
    return [
      { label: 'Total Return', value: '—', isPositive: true },
      { label: 'Annual Return', value: '—', isPositive: true },
      { label: 'Sharpe Ratio', value: '—', isPositive: true },
      { label: 'Max Drawdown', value: '—', isPositive: false },
      { label: 'Win Rate', value: '—', isPositive: true },
      { label: 'Profit Factor', value: '—', isPositive: true },
    ]
  }

  const initialNav = navs[0]
  const finalNav = navs[navs.length - 1]
  const totalReturn = initialNav > 0 ? (finalNav / initialNav - 1) : 0

  // Approximate annualized return (252 trading days ≈ 1 year)
  const years = navs.length / 252
  const annualReturn = years > 0 ? (Math.pow(1 + totalReturn, 1 / years) - 1) : 0

  // Sharpe ratio from daily returns
  const rets = dailyReturns(navs)
  const avgRet = rets.length > 0 ? rets.reduce((a, b) => a + b, 0) / rets.length : 0
  const stdRet =
    rets.length > 1
      ? Math.sqrt(rets.reduce((s, r) => s + (r - avgRet) ** 2, 0) / (rets.length - 1))
      : 0
  const sharpe = stdRet > 0 ? (avgRet / stdRet) * Math.sqrt(252) : 0

  // Max drawdown
  const mdd = maxDrawdown(navs)

  // Win rate
  const wins = rets.filter((r) => r > 0).length
  const winRate = rets.length > 0 ? wins / rets.length : 0

  // Profit factor
  const grossProfit = rets.filter((r) => r > 0).reduce((a, b) => a + b, 0)
  const grossLoss = Math.abs(rets.filter((r) => r < 0).reduce((a, b) => a + b, 0))
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0

  return [
    { label: 'Total Return', value: `${(totalReturn * 100).toFixed(1)}%`, isPositive: totalReturn >= 0 },
    { label: 'Annual Return', value: `${(annualReturn * 100).toFixed(1)}%`, isPositive: annualReturn >= 0 },
    { label: 'Sharpe Ratio', value: sharpe.toFixed(2), isPositive: sharpe >= 0 },
    { label: 'Max Drawdown', value: `${(mdd * 100).toFixed(1)}%`, isPositive: false },
    { label: 'Win Rate', value: `${(winRate * 100).toFixed(1)}%`, isPositive: winRate >= 0.5 },
    { label: 'Profit Factor', value: profitFactor === Infinity ? '∞' : profitFactor.toFixed(2), isPositive: profitFactor >= 1 },
  ]
})

// ── ECharts options ──

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
    axisLabel: { fontSize: 10, color: '#999999', formatter: (v: number) => `$${(v / 1000).toFixed(0)}K` },
  },
  series: [
    {
      name: 'Strategy',
      type: 'line',
      data: equityCurve.value,
      smooth: true,
      symbol: 'none',
      lineStyle: { color: '#FF6700', width: 2 },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: '#FF670020' },
            { offset: 1, color: '#FF670002' },
          ],
        },
      },
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
    data: yearlyReturnData.value.map((y) => y.year),
    axisLabel: { fontSize: 10, color: '#666666' },
  },
  yAxis: {
    type: 'value' as const,
    splitLine: { lineStyle: { color: '#F5F5F5' } },
    axisLabel: { fontSize: 10, color: '#999999', formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
  },
  series: [
    {
      type: 'bar',
      data: yearlyReturnData.value.map((y) => ({
        value: y.return,
        itemStyle: { color: y.return >= 0 ? '#16A34A' : '#DC2626', borderRadius: [4, 4, 0, 0] },
      })),
      barWidth: 28,
    },
  ],
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
    <XmCard title="Backtest Equity Curve" subtitle="Strategy vs Benchmark">
      <div v-if="loading" class="flex items-center justify-center h-[360px] text-xm-text-tertiary text-sm">
        Loading portfolio data...
      </div>
      <div v-else-if="!hasData" class="flex flex-col items-center justify-center h-[360px] text-xm-text-tertiary text-sm gap-2">
        <span>暂无回测数据，请先运行回测或积累交易数据</span>
      </div>
      <VChart v-else :option="equityChartOption" style="height: 360px" autoresize />
    </XmCard>

    <!-- Yearly Returns -->
    <XmCard title="Annual Returns">
      <div v-if="yearlyReturnData.length === 0 && !loading" class="flex items-center justify-center h-[260px] text-xm-text-tertiary text-sm">
        No yearly return data available
      </div>
      <VChart v-else :option="yearlyChartOption" style="height: 260px" autoresize />
    </XmCard>
  </div>
</template>
