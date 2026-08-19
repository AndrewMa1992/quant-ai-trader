<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import AccountSummary from '@/components/dashboard/AccountSummary.vue'
import MarketStatusBar from '@/components/dashboard/MarketStatusBar.vue'
import SignalTrendChart from '@/components/SignalTrendChart.vue'
import XmCard from '@/components/ui/XmCard.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import { usePortfolioStore } from '@/stores/usePortfolioStore'
import { useRiskStore } from '@/stores/useRiskStore'
import { useExecutionStore } from '@/stores/useExecutionStore'
import { useModelStore } from '@/stores/useModelStore'
import { tradeApi } from '@/api/tradeApi'
import { modelApi } from '@/api/modelApi'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const portfolioStore = usePortfolioStore()
const riskStore = useRiskStore()
const execStore = useExecutionStore()
const modelStore = useModelStore()

const navHistory = ref<number[]>([])
/** SignalTrendChart expects { cycle, strength, decision } */
const signalHistory = ref<Array<{ cycle: number; strength: number; decision: string }>>([])

let refreshTimer: ReturnType<typeof setInterval> | undefined

const rollbackLoading = ref(false)
const toastMessage = ref('')
const toastVisible = ref(false)
let toastTimer: ReturnType<typeof setTimeout> | undefined

function showToast(message: string, duration = 3000) {
  toastMessage.value = message
  toastVisible.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toastVisible.value = false
  }, duration)
}

const canRollback = computed(() => {
  const us = execStore.marketStatus?.US
  const hk = execStore.marketStatus?.HK
  const usOpen = us?.is_open ?? false
  const hkOpen = hk?.is_open ?? false
  return !usOpen && !hkOpen
})

async function handleRollback() {
  if (!confirm('确定要回滚到上一个稳定版本吗？')) return
  rollbackLoading.value = true
  try {
    const result = await execStore.rollback()
    if (result?.success) {
      showToast('回滚成功！熔断器已重置。')
    } else {
      showToast('回滚失败，请查看日志。')
    }
  } catch {
    showToast('回滚请求失败，请稍后重试。')
  } finally {
    rollbackLoading.value = false
  }
}

async function fetchSignals() {
  try {
    await modelStore.fetchAllSignals()
    const signals = modelStore.signals
    if (signals.length > 0) {
      signalHistory.value = signals.map((s, i) => ({
        cycle: i + 1,
        strength: Number(s.signal ?? s.confidence ?? 0),
        decision: String(s.direction || 'hold').toLowerCase(),
      }))
      return
    }
  } catch {
    // try direct API
  }

  try {
    const data = await modelApi.getAllSignals()
    const signals = data?.signals ?? []
    signalHistory.value = signals.map((s: { signal?: number; confidence?: number; direction?: string }, i: number) => ({
      cycle: i + 1,
      strength: Number(s.signal ?? s.confidence ?? 0),
      decision: String(s.direction || 'hold').toLowerCase(),
    }))
  } catch {
    signalHistory.value = []
  }
}

onMounted(async () => {
  await Promise.allSettled([
    portfolioStore.fetchPositions(),
    execStore.fetchAlerts(),
    execStore.fetchMarketStatus(),
    riskStore.fetchBreakerStatus(),
    fetchNavHistory(),
    fetchSignals(),
  ])
  refreshTimer = setInterval(() => {
    portfolioStore.fetchPositions()
    fetchSignals()
  }, 30000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})

async function fetchNavHistory(): Promise<void> {
  try {
    const result = await tradeApi.getPortfolioHistory(90)
    if (result.history && result.history.length > 0) {
      navHistory.value = result.history.map((p) => p.nav)
      return
    }
  } catch {
    // fallback
  }

  try {
    const portfolio = await tradeApi.getPortfolio()
    if (portfolio.value_history && portfolio.value_history.length > 0) {
      navHistory.value = portfolio.value_history.map((v) => v.value)
      return
    }
  } catch {
    // empty
  }

  navHistory.value = []
}

const navChartOption = computed(() => ({
  grid: { top: 8, right: 16, bottom: 4, left: 50 },
  tooltip: {
    trigger: 'axis' as const,
    backgroundColor: '#fff',
    borderColor: '#EEEEEE',
    textStyle: { color: '#1A1A1A', fontSize: 12 },
  },
  xAxis: {
    type: 'category' as const,
    show: false,
    data: navHistory.value.map((_, i) => i),
  },
  yAxis: {
    type: 'value' as const,
    show: true,
    splitLine: { lineStyle: { color: '#F5F5F5' } },
    axisLabel: { fontSize: 10, color: '#999999' },
  },
  series: [{
    type: 'line',
    data: navHistory.value,
    smooth: true,
    symbol: 'none',
    lineStyle: { color: '#FF6700', width: 2 },
    areaStyle: {
      color: {
        type: 'linear',
        x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [
          { offset: 0, color: '#FF670030' },
          { offset: 1, color: '#FF670005' },
        ],
      },
    },
  }],
}))

const nav = computed(() => portfolioStore.summary?.total_market_value ?? 0)
const dailyPnl = computed(() => riskStore.dailyPnl)
const dailyPnlPct = computed(() => riskStore.dailyPnlPct)
const drawdown = computed(() => riskStore.currentDrawdown)
const sharpe = computed(() => parseFloat(String(riskStore.varData?.sharpe_ratio ?? 0)))

const positionCount = computed(() => portfolioStore.positions?.length ?? 0)
const alertCount = computed(() => execStore.alerts.length)
const marketMap = computed(() => execStore.marketStatus ?? {})
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <Transition name="toast-slide">
      <div
        v-if="toastVisible"
        class="fixed top-5 right-5 z-50 px-5 py-3 rounded-lg shadow-lg text-white text-sm font-medium"
        style="background-color: #FF6700;"
      >
        {{ toastMessage }}
      </div>
    </Transition>

    <MarketStatusBar :markets="marketMap" />

    <div class="flex items-start gap-4">
      <div class="flex-1">
        <AccountSummary
          :nav="nav"
          :daily-pnl="dailyPnl"
          :daily-pnl-pct="dailyPnlPct"
          :drawdown="drawdown"
          :sharpe-ratio="sharpe"
          :nav-history="navHistory"
        />
      </div>
      <button
        :disabled="!canRollback || rollbackLoading"
        :title="!canRollback ? '仅非交易时段可用' : '回滚到上一个稳定版本'"
        class="flex-shrink-0 px-4 py-2.5 rounded-lg text-white text-sm font-semibold transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed hover:shadow-md active:scale-95"
        :style="{ backgroundColor: canRollback ? '#FF6700' : '#CCCCCC' }"
        @click="handleRollback"
      >
        <span v-if="rollbackLoading" class="inline-flex items-center gap-1.5">
          <svg class="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          回滚中...
        </span>
        <span v-else>一键回滚</span>
      </button>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <XmCard title="NAV Trend" class="lg:col-span-2 !p-5">
        <template #header>
          <XmBadge variant="info">Live</XmBadge>
        </template>
        <div
          v-if="navHistory.length === 0"
          class="flex items-center justify-center h-[280px] text-xm-text-tertiary text-sm"
        >
          No NAV history available
        </div>
        <VChart v-else :option="navChartOption" style="height: 280px" autoresize />
      </XmCard>

      <XmCard title="Quick Stats" class="!p-5">
        <div class="space-y-4">
          <div class="flex justify-between items-center py-2 border-b border-xm-border-light">
            <span class="text-sm text-xm-text-secondary">Positions</span>
            <span class="text-sm font-mono font-semibold">{{ positionCount }}</span>
          </div>
          <div class="flex justify-between items-center py-2 border-b border-xm-border-light">
            <span class="text-sm text-xm-text-secondary">Alerts (24h)</span>
            <span class="text-sm font-mono font-semibold" :class="alertCount > 0 ? 'text-risk-red' : ''">
              {{ alertCount }}
            </span>
          </div>
          <div class="flex justify-between items-center py-2 border-b border-xm-border-light">
            <span class="text-sm text-xm-text-secondary">US Market</span>
            <span
              class="text-sm font-mono"
              :class="execStore.marketStatus?.US?.is_open ? 'text-profit' : 'text-xm-text-tertiary'"
            >
              {{ execStore.marketStatus?.US?.is_open ? 'Open' : 'Closed' }}
            </span>
          </div>
          <div class="flex justify-between items-center py-2 border-b border-xm-border-light">
            <span class="text-sm text-xm-text-secondary">HK Market</span>
            <span
              class="text-sm font-mono"
              :class="execStore.marketStatus?.HK?.is_open ? 'text-profit' : 'text-xm-text-tertiary'"
            >
              {{ execStore.marketStatus?.HK?.is_open ? 'Open' : 'Closed' }}
            </span>
          </div>
          <div class="flex justify-between items-center py-2">
            <span class="text-sm text-xm-text-secondary">Signals</span>
            <span class="text-sm font-mono font-semibold">{{ signalHistory.length }}</span>
          </div>
        </div>
      </XmCard>
    </div>

    <XmCard title="Signal Trend" class="!p-5">
      <div
        v-if="signalHistory.length === 0"
        class="flex items-center justify-center h-[120px] text-xm-text-tertiary text-sm"
      >
        No signals available. Models may be offline.
      </div>
      <SignalTrendChart v-else :history="signalHistory" height="120px" />
    </XmCard>

    <XmCard title="Recent Positions" class="!p-5">
      <table v-if="portfolioStore.positions && portfolioStore.positions.length > 0" class="xm-table">
        <thead>
          <tr>
            <th>Ticker</th>
            <th class="text-right">Shares</th>
            <th class="text-right">Cost Basis</th>
            <th class="text-right">Market Value</th>
            <th class="text-right">P&L</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="pos in portfolioStore.positions.slice(0, 10)" :key="pos.ticker">
            <td class="font-mono font-semibold">{{ pos.ticker }}</td>
            <td class="text-right font-mono">{{ pos.quantity?.toFixed(0) }}</td>
            <td class="text-right font-mono">${{ pos.cost_basis?.toFixed(2) }}</td>
            <td class="text-right font-mono">
              ${{ pos.market_value?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
            </td>
            <td
              class="text-right font-mono"
              :class="(pos.unrealized_pnl ?? 0) >= 0 ? 'xm-pnl-positive' : 'xm-pnl-negative'"
            >
              {{ (pos.unrealized_pnl ?? 0) >= 0 ? '+' : '' }}${{ pos.unrealized_pnl?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="text-center py-10 text-xm-text-tertiary text-sm">
        No active positions. Start trading to see your portfolio.
      </div>
    </XmCard>
  </div>
</template>

<style scoped>
.toast-slide-enter-active,
.toast-slide-leave-active {
  transition: all 0.3s ease;
}
.toast-slide-enter-from,
.toast-slide-leave-to {
  opacity: 0;
  transform: translateY(-12px);
}
</style>
