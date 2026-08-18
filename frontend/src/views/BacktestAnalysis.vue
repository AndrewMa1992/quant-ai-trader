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

const tickersInput = ref('AAPL,MSFT,GOOGL,SPY')
const startDate = ref('2023-01-01')
const endDate = ref(new Date().toISOString().slice(0, 10))
const capital = ref(1_000_000)
const running = ref(false)
const runError = ref('')

const historyData = ref<PortfolioHistoryPoint[]>([])
const yearlyReturnData = ref<YearlyReturn[]>([])
const historyLoading = ref(false)

const hasBacktest = computed(() => !!portfolioStore.backtestResult)
const hasHistory = computed(() => !historyLoading.value && historyData.value.length > 0)

onMounted(async () => {
  await loadSecondaryCharts()
})

async function loadSecondaryCharts() {
  historyLoading.value = true
  try {
    const [history, yearly] = await Promise.all([
      analysisApi.getPortfolioHistory().catch(() => [] as PortfolioHistoryPoint[]),
      analysisApi.getYearlyReturns().catch(() => [] as YearlyReturn[]),
    ])
    historyData.value = history ?? []
    yearlyReturnData.value = yearly ?? []
  } catch {
    historyData.value = []
    yearlyReturnData.value = []
  } finally {
    historyLoading.value = false
  }
}

async function submitBacktest() {
  runError.value = ''
  const tickers = tickersInput.value
    .split(',')
    .map((t) => t.trim().toUpperCase())
    .filter(Boolean)
  if (tickers.length === 0) {
    runError.value = 'Enter at least one ticker'
    return
  }
  if (!startDate.value || !endDate.value) {
    runError.value = 'Start and end dates are required'
    return
  }

  running.value = true
  try {
    await portfolioStore.runBacktest(tickers, startDate.value, endDate.value, capital.value)
    if (!portfolioStore.backtestResult && portfolioStore.error) {
      runError.value = portfolioStore.error
    }
    await loadSecondaryCharts()
  } catch (e: unknown) {
    runError.value = e instanceof Error ? e.message : 'Backtest failed'
  } finally {
    running.value = false
  }
}

interface PerfMetric {
  label: string
  value: string
  isPositive: boolean
}

const backtestMetrics = computed<PerfMetric[]>(() => {
  const bt = portfolioStore.backtestResult
  if (!bt) {
    return [
      { label: 'Total Return', value: '—', isPositive: true },
      { label: 'Annual Return', value: '—', isPositive: true },
      { label: 'Sharpe Ratio', value: '—', isPositive: true },
      { label: 'Max Drawdown', value: '—', isPositive: false },
      { label: 'Final Value', value: '—', isPositive: true },
      { label: 'Initial Capital', value: '—', isPositive: true },
    ]
  }
  return [
    {
      label: 'Total Return',
      value: `${(bt.total_return * 100).toFixed(1)}%`,
      isPositive: bt.total_return >= 0,
    },
    {
      label: 'Annual Return',
      value: `${(bt.annual_return * 100).toFixed(1)}%`,
      isPositive: bt.annual_return >= 0,
    },
    {
      label: 'Sharpe Ratio',
      value: bt.sharpe_ratio.toFixed(2),
      isPositive: bt.sharpe_ratio >= 0,
    },
    {
      label: 'Max Drawdown',
      value: `${(bt.max_drawdown * 100).toFixed(1)}%`,
      isPositive: false,
    },
    {
      label: 'Final Value',
      value: `$${Math.round(bt.final_value).toLocaleString()}`,
      isPositive: bt.final_value >= capital.value,
    },
    {
      label: 'Initial Capital',
      value: `$${capital.value.toLocaleString()}`,
      isPositive: true,
    },
  ]
})

const equityCurve = computed<number[]>(() => historyData.value.map((p) => p.nav))
const benchmarkCurve = computed<number[]>(() => historyData.value.map((p) => p.benchmark))

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
          x: 0, y: 0, x2: 0, y2: 1,
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
    <XmCard title="Run Backtest" class="!p-5">
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <div class="lg:col-span-2">
          <label class="block text-xxs text-xm-text-tertiary mb-1">Tickers</label>
          <input
            v-model="tickersInput"
            class="xm-input w-full"
            placeholder="AAPL,MSFT,GOOGL,SPY"
            :disabled="running"
          />
        </div>
        <div>
          <label class="block text-xxs text-xm-text-tertiary mb-1">Start Date</label>
          <input v-model="startDate" type="date" class="xm-input w-full" :disabled="running" />
        </div>
        <div>
          <label class="block text-xxs text-xm-text-tertiary mb-1">End Date</label>
          <input v-model="endDate" type="date" class="xm-input w-full" :disabled="running" />
        </div>
        <div>
          <label class="block text-xxs text-xm-text-tertiary mb-1">Capital</label>
          <input v-model.number="capital" type="number" min="1000" step="1000" class="xm-input w-full" :disabled="running" />
        </div>
      </div>
      <div class="flex items-center gap-3">
        <button class="xm-btn-primary" :disabled="running" @click="submitBacktest">
          {{ running ? 'Running...' : 'Run Backtest' }}
        </button>
        <span v-if="runError" class="text-sm text-loss">{{ runError }}</span>
      </div>
    </XmCard>

    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      <XmCard v-for="m in backtestMetrics" :key="m.label" class="!p-3">
        <div class="xm-metric-label text-xxs">{{ m.label }}</div>
        <div
          class="text-base font-mono font-bold mt-1"
          :class="m.isPositive ? 'xm-pnl-positive' : 'xm-pnl-negative'"
        >
          {{ m.value }}
        </div>
      </XmCard>
    </div>

    <div
      v-if="!hasBacktest && !running"
      class="text-center py-4 text-xm-text-tertiary text-sm"
    >
      Submit a backtest to see strategy metrics. Portfolio history charts below load independently.
    </div>

    <XmCard title="Portfolio History" subtitle="Secondary — from analysis API">
      <div v-if="historyLoading" class="flex items-center justify-center h-[360px] text-xm-text-tertiary text-sm">
        Loading portfolio history...
      </div>
      <div
        v-else-if="!hasHistory"
        class="flex flex-col items-center justify-center h-[360px] text-xm-text-tertiary text-sm gap-2"
      >
        <span>No portfolio history available yet.</span>
      </div>
      <VChart v-else :option="equityChartOption" style="height: 360px" autoresize />
    </XmCard>

    <XmCard title="Annual Returns">
      <div
        v-if="yearlyReturnData.length === 0 && !historyLoading"
        class="flex items-center justify-center h-[260px] text-xm-text-tertiary text-sm"
      >
        No yearly return data available
      </div>
      <VChart v-else-if="yearlyReturnData.length > 0" :option="yearlyChartOption" style="height: 260px" autoresize />
    </XmCard>
  </div>
</template>
