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

use([LineChart, GaugeChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const riskStore = useRiskStore()
const execStore = useExecutionStore()

const drawdownHistory = ref<number[]>([0, 0.02, 0.05, 0.03, 0.08, 0.06, 0.04, 0.07, 0.05, 0.03])

const cbTriggered = computed(() => execStore.cbStatus.halted)
const dailyPnlPct = ref(-0.012) // -1.2%
const dailyLossLimit = 0.05
const currentDrawdown = ref(0.03)
const maxDrawdown = 0.25
const var95 = ref(28500)
const portfolioValue = 1000000

// P0-3: Breaker control loading states
const resetLoading = ref(false)
const toggleLoading = ref(false)

onMounted(async () => {
  riskStore.fetchVaR(['AAPL', 'MSFT'], [0.3, 0.3])
  await riskStore.fetchBreakerStatus()
})

// P0-3: Reset circuit breaker
async function handleResetBreaker() {
  resetLoading.value = true
  try {
    await riskStore.resetCircuitBreaker()
  } finally {
    resetLoading.value = false
  }
}

// P0-3: Toggle breaker mode
async function handleToggleBreaker() {
  toggleLoading.value = true
  try {
    const newMode = riskStore.breakerMode === 'hard' ? 'warn' : 'hard'
    await riskStore.toggleBreakerMode(newMode)
  } finally {
    toggleLoading.value = false
  }
}

const drawdownChartOption = computed(() => ({
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
    data: drawdownHistory.value.map((_, i) => i),
  },
  yAxis: {
    type: 'value' as const,
    show: true,
    splitLine: { lineStyle: { color: '#F5F5F5' } },
    axisLabel: { fontSize: 10, color: '#999999', formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
  },
  series: [{
    type: 'line',
    data: drawdownHistory.value,
    smooth: true,
    symbol: 'none',
    lineStyle: { color: '#EF4444', width: 2 },
    areaStyle: {
      color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
        { offset: 0, color: '#EF444430' }, { offset: 1, color: '#EF444405' }
      ]},
    },
  }],
}))

const riskMetrics = computed(() => [
  { label: 'VaR (95%)', value: `$${(var95.value).toLocaleString()}`, sub: `${((var95.value / portfolioValue) * 100).toFixed(2)}% of NAV` },
  { label: 'Expected Shortfall', value: `$${(var95.value * 1.4).toLocaleString()}`, sub: 'Conditional VaR' },
  { label: 'Max Drawdown', value: `${(currentDrawdown.value * 100).toFixed(2)}%`, sub: `Limit: ${(maxDrawdown * 100).toFixed(0)}%` },
  { label: 'Volatility (30d)', value: '12.5%', sub: 'Annualized' },
])
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <!-- Circuit Breaker + Gauge Row -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <CircuitBreakerStatus
        :triggered="cbTriggered"
        :daily-pnl-pct="dailyPnlPct"
        :daily-loss-limit="dailyLossLimit"
        :drawdown="currentDrawdown"
        :max-drawdown="maxDrawdown"
        :cooldown-remaining="0"
      />

      <!-- Drawdown Gauge -->
      <XmCard title="Drawdown Gauge" class="!p-5 flex flex-col items-center justify-center">
        <XmGauge
          :value="currentDrawdown * 100"
          :max="maxDrawdown * 100"
          label="Drawdown %"
          :size="160"
        />
        <p class="text-xs text-xm-text-tertiary mt-1">Limit: {{ (maxDrawdown * 100).toFixed(0) }}%</p>
      </XmCard>

      <!-- VaR Gauge -->
      <XmCard title="Value at Risk" class="!p-5 flex flex-col items-center justify-center">
        <XmGauge
          :value="(var95 / portfolioValue) * 100"
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
        <div class="flex items-center gap-2 px-4 py-2 rounded-lg" :class="riskStore.breakerMode === 'hard' ? 'bg-risk-red/10 border border-risk-red/30' : 'bg-risk-yellow/10 border border-risk-yellow/30'">
          <span class="text-sm font-semibold">当前模式:</span>
          <span class="text-sm font-mono font-bold" :class="riskStore.breakerMode === 'hard' ? 'text-risk-red' : 'text-risk-yellow'">
            {{ riskStore.breakerMode === 'hard' ? '🔴 硬熔断' : '🟡 仅告警' }}
          </span>
        </div>

        <!-- Toggle Mode Button -->
        <button
          class="xm-btn px-4 py-2 rounded-lg text-sm font-semibold transition-all duration-200 hover:opacity-90 disabled:opacity-50"
          :class="riskStore.breakerMode === 'hard' ? 'bg-risk-yellow text-white' : 'bg-risk-red text-white'"
          :disabled="toggleLoading"
          @click="handleToggleBreaker"
        >
          {{ toggleLoading ? '⏳ 切换中...' : (riskStore.breakerMode === 'hard' ? '🔧 切换至仅告警' : '🔧 切换至硬熔断') }}
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
