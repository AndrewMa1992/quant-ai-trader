<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, GaugeChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import XmCard from '@/components/ui/XmCard.vue'
import XmGauge from '@/components/ui/XmGauge.vue'
import CircuitBreakerStatus from '@/components/risk/CircuitBreakerStatus.vue'
import { useRiskStore } from '@/stores/useRiskStore'
import { useExecutionStore } from '@/stores/useExecutionStore'
import { riskApi } from '@/api/riskApi'
import { tradeApi, type DashboardData, type TradePortfolio } from '@/api/tradeApi'

use([LineChart, GaugeChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const riskStore = useRiskStore()
const execStore = useExecutionStore()

// ── Policy constants (risk limits, not live data) ────────────
const DAILY_LOSS_LIMIT = 0.05   // 5% daily loss limit
const MAX_DRAWDOWN_LIMIT = 0.25 // 25% max drawdown limit

// ── Reactive data fetched from APIs ──────────────────────────
const drawdownHistory = ref<number[]>([0])
const dashboardData = ref<DashboardData>({})
const portfolioData = ref<TradePortfolio | null>(null)

// ── Circuit breaker pass-through from riskStore (live after fetchBreakerStatus) ──
const cbTriggered = computed(() => execStore.cbStatus.halted)
const dailyPnlPct = computed(() => riskStore.dailyPnlPct)
const currentDrawdown = computed(() => riskStore.currentDrawdown)

// ── Derived metrics ──────────────────────────────────────────

/** Portfolio total value from /api/trade/portfolio, fallback to dashboard, then $1M */
const portfolioValue = computed<number>(() => {
  const fromPortfolio = portfolioData.value?.metrics?.total_value
  if (fromPortfolio != null && (fromPortfolio as number) > 0) return fromPortfolio as number
  const fromDashboard = dashboardData.value.total_value
  if (fromDashboard != null && fromDashboard > 0) return fromDashboard
  return 1_000_000
})

/** VaR 95% — absolute dollar amount from riskStore.varData × portfolio value */
const var95 = computed<number>(() => {
  const vd = riskStore.varData as Record<string, number> | null
  if (!vd) return 0
  // var_normal (parametric), var_student_t, or var (historical/montecarlo)
  const varReturn = vd.var_normal ?? vd.var_student_t ?? vd.var ?? 0
  return Math.abs(varReturn) * portfolioValue.value
})

/** Historical maximum drawdown from dashboard API (e.g. 0.08 = 8%), fallback to limit */
const historicalMaxDrawdown = computed<number>(() => {
  const dd = dashboardData.value.max_drawdown_pct
  return dd != null ? Math.abs(dd) : MAX_DRAWDOWN_LIMIT
})

// ── P0-3: Breaker control loading states ────────────────────
const resetLoading = ref(false)
const toggleLoading = ref(false)

// ── Data fetching ────────────────────────────────────────────

async function fetchAllData(): Promise<void> {
  // Fetch breaker status + dashboard + portfolio + drawdown history in parallel
  await Promise.allSettled([
    riskStore.fetchBreakerStatus(),
    tradeApi.getDashboard().then((d) => { dashboardData.value = d }).catch(() => { /* keep last */ }),
    tradeApi.getPortfolio().then((p) => { portfolioData.value = p }).catch(() => { /* keep last */ }),
    riskApi.getDrawdownHistory().then((d) => {
      const history = d.drawdown_history ?? []
      if (history.length > 0) {
        // API returns negative drawdowns; use abs for display
        drawdownHistory.value = history.map((h) => Math.abs(h.drawdown))
      }
    }).catch(() => { /* keep last */ }),
  ])

  // Fetch VaR using real portfolio tickers (or fallback)
  try {
    const positions = portfolioData.value?.positions ?? []
    if (positions.length > 0) {
      const tickers = positions.map((p) => p.ticker)
      const totalAlloc = positions.reduce((s, p) => s + (p.allocation || 0), 0) || 1
      const weights = positions.map((p) => (p.allocation || 0) / totalAlloc)
      riskStore.fetchVaR(tickers, weights)
    } else {
      riskStore.fetchVaR(['AAPL', 'MSFT'], [0.3, 0.3])
    }
  } catch {
    riskStore.fetchVaR(['AAPL', 'MSFT'], [0.3, 0.3])
  }
}

onMounted(() => {
  fetchAllData()
})

// ── P0-3: Breaker actions ────────────────────────────────────

async function handleResetBreaker(): Promise<void> {
  resetLoading.value = true
  try {
    await riskStore.resetCircuitBreaker()
  } finally {
    resetLoading.value = false
  }
}

async function handleToggleBreaker(): Promise<void> {
  toggleLoading.value = true
  try {
    const newMode = riskStore.breakerMode === 'hard' ? 'warn' : 'hard'
    await riskStore.toggleBreakerMode(newMode)
  } finally {
    toggleLoading.value = false
  }
}

// ── Charts ───────────────────────────────────────────────────

const drawdownChartOption = computed(() => {
  const data = drawdownHistory.value.length > 0 ? drawdownHistory.value : [0]
  return {
    grid: { top: 8, right: 16, bottom: 4, left: 50 },
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: '#fff',
      borderColor: '#EEEEEE',
      textStyle: { color: '#1A1A1A', fontSize: 12 },
      valueFormatter: (v: number) => `${(v * 100).toFixed(2)}%`,
    },
    xAxis: {
      type: 'category' as const,
      show: false,
      data: data.map((_, i) => i),
    },
    yAxis: {
      type: 'value' as const,
      show: true,
      splitLine: { lineStyle: { color: '#F5F5F5' } },
      axisLabel: {
        fontSize: 10,
        color: '#999999',
        formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
      },
    },
    series: [{
      type: 'line',
      data,
      smooth: true,
      symbol: 'none',
      lineStyle: { color: '#EF4444', width: 2 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: '#EF444430' },
            { offset: 1, color: '#EF444405' },
          ],
        },
      },
    }],
  }
})

// ── Risk metrics cards ───────────────────────────────────────

const riskMetrics = computed(() => {
  const ddPct = Math.abs(currentDrawdown.value) * 100
  const peakDdPct = historicalMaxDrawdown.value * 100
  const varAbs = var95.value
  const esAbs = varAbs * 1.4
  const pv = Math.max(portfolioValue.value, 1)
  const sharpe = dashboardData.value.sharpe_ratio
  const winRate = dashboardData.value.win_rate

  return [
    {
      label: 'VaR (95%)',
      value: `$${Math.round(varAbs).toLocaleString()}`,
      sub: `${((varAbs / pv) * 100).toFixed(2)}% of NAV`,
    },
    {
      label: 'Expected Shortfall',
      value: `$${Math.round(esAbs).toLocaleString()}`,
      sub: 'Conditional VaR',
    },
    {
      label: 'Max Drawdown',
      value: `${ddPct.toFixed(2)}%`,
      sub: `Peak: ${peakDdPct.toFixed(2)}% | Limit: ${(MAX_DRAWDOWN_LIMIT * 100).toFixed(0)}%`,
    },
    {
      label: 'Sharpe Ratio',
      value: sharpe != null ? sharpe.toFixed(2) : '--',
      sub: winRate != null
        ? `Win Rate: ${(winRate * 100).toFixed(1)}%`
        : 'Annualized',
    },
  ]
})

/** Cooldown remaining from riskStore (in seconds) */
const cooldownRemaining = computed(() => riskStore.circuitBreakerCooldown)
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <!-- Circuit Breaker + Gauge Row -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <CircuitBreakerStatus
        :triggered="cbTriggered"
        :daily-pnl-pct="dailyPnlPct"
        :daily-loss-limit="DAILY_LOSS_LIMIT"
        :drawdown="Math.abs(currentDrawdown)"
        :max-drawdown="MAX_DRAWDOWN_LIMIT"
        :cooldown-remaining="cooldownRemaining"
      />

      <!-- Drawdown Gauge -->
      <XmCard title="Drawdown Gauge" class="!p-5 flex flex-col items-center justify-center">
        <XmGauge
          :value="Math.abs(currentDrawdown) * 100"
          :max="MAX_DRAWDOWN_LIMIT * 100"
          label="Drawdown %"
          :size="160"
        />
        <p class="text-xs text-xm-text-tertiary mt-1">
          Limit: {{ (MAX_DRAWDOWN_LIMIT * 100).toFixed(0) }}%
        </p>
      </XmCard>

      <!-- VaR Gauge -->
      <XmCard title="Value at Risk" class="!p-5 flex flex-col items-center justify-center">
        <XmGauge
          :value="Math.max(portfolioValue, 1) > 0 ? (var95 / Math.max(portfolioValue, 1)) * 100 : 0"
          :max="10"
          label="VaR %"
          :size="160"
          :color-stops="[[0.2, '#22C55E'], [0.5, '#EAB308'], [1.0, '#EF4444']]"
        />
        <p class="text-xs text-xm-text-tertiary mt-1">95% Confidence</p>
      </XmCard>
    </div>

    <!-- P0-3: Breaker Controls -->
    <XmCard title="⚡ Circuit Breaker Controls" class="!p-5">
      <div class="flex flex-wrap items-center gap-4">
        <!-- Breaker Mode Display -->
        <div
          class="flex items-center gap-2 px-4 py-2 rounded-lg"
          :class="riskStore.breakerMode === 'hard'
            ? 'bg-risk-red/10 border border-risk-red/30'
            : 'bg-risk-yellow/10 border border-risk-yellow/30'"
        >
          <span class="text-sm font-semibold">当前模式:</span>
          <span
            class="text-sm font-mono font-bold"
            :class="riskStore.breakerMode === 'hard' ? 'text-risk-red' : 'text-risk-yellow'"
          >
            {{ riskStore.breakerMode === 'hard' ? '🔴 硬熔断' : '🟡 仅告警' }}
          </span>
        </div>

        <!-- Toggle Mode Button -->
        <button
          class="xm-btn px-4 py-2 rounded-lg text-sm font-semibold transition-all duration-200 hover:opacity-90 disabled:opacity-50"
          :class="riskStore.breakerMode === 'hard'
            ? 'bg-risk-yellow text-white'
            : 'bg-risk-red text-white'"
          :disabled="toggleLoading"
          @click="handleToggleBreaker"
        >
          {{ toggleLoading
            ? '⏳ 切换中...'
            : (riskStore.breakerMode === 'hard' ? '🔧 切换至仅告警' : '🔧 切换至硬熔断') }}
        </button>

        <!-- Reset Breaker Button -->
        <button
          class="xm-btn px-4 py-2 rounded-lg text-sm font-semibold transition-all duration-200 hover:opacity-90 disabled:opacity-50"
          style="background-color: #FF6700; color: white;"
          :disabled="resetLoading"
          @click="handleResetBreaker"
        >
          {{ resetLoading ? '⏳ 重置中...' : '⚡ 重置断路器' }}
        </button>
      </div>
    </XmCard>

    <!-- Risk Metrics Cards -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <XmCard v-for="metric in riskMetrics" :key="metric.label" class="!p-4">
        <div class="xm-metric-label">{{ metric.label }}</div>
        <div class="xm-metric-value text-lg mt-1">{{ metric.value }}</div>
        <div class="text-xs text-xm-text-tertiary mt-1">{{ metric.sub }}</div>
      </XmCard>
    </div>

    <!-- Drawdown History Chart -->
    <XmCard title="Drawdown History">
      <VChart :option="drawdownChartOption" style="height: 260px" autoresize />
    </XmCard>
  </div>
</template>
