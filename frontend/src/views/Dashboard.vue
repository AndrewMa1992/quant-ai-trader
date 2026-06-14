<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import AccountSummary from '@/components/dashboard/AccountSummary.vue'
import XmCard from '@/components/ui/XmCard.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import { usePortfolioStore } from '@/stores/usePortfolioStore'
import { useRiskStore } from '@/stores/useRiskStore'
import { useExecutionStore } from '@/stores/useExecutionStore'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const portfolioStore = usePortfolioStore()
const riskStore = useRiskStore()
const execStore = useExecutionStore()

const navHistory = ref<number[]>([100, 101, 103, 102, 105, 107, 106, 108, 110, 109])
const signalHistory = ref<Array<{ time: string; buy: number; sell: number }>>([])

let refreshTimer: ReturnType<typeof setInterval> | undefined

onMounted(async () => {
  await Promise.all([
    portfolioStore.fetchPositions(),
    execStore.fetchAlerts(),
    execStore.fetchMarketStatus(),
  ])
  refreshTimer = setInterval(() => {
    portfolioStore.fetchPositions()
  }, 30000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})

// NAV chart option
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
const dailyPnl = computed(() => parseFloat(String(riskStore.varData?.daily_pnl ?? 0)))
const dailyPnlPct = computed(() => parseFloat(String(riskStore.varData?.daily_pnl_pct ?? 0)))
const drawdown = computed(() => parseFloat(String(riskStore.varData?.max_drawdown ?? 0)))
const sharpe = computed(() => parseFloat(String(riskStore.varData?.sharpe_ratio ?? 0)))

const positionCount = computed(() => portfolioStore.positions?.length ?? 0)
const alertCount = computed(() => execStore.alerts.length)
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <!-- KPI Cards Row -->
    <AccountSummary
      :nav="nav"
      :daily-pnl="dailyPnl"
      :daily-pnl-pct="dailyPnlPct"
      :drawdown="drawdown"
      :sharpe-ratio="sharpe"
      :nav-history="navHistory"
    />

    <!-- Charts Row -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <!-- NAV Chart -->
      <XmCard title="NAV Trend" class="lg:col-span-2 !p-5">
        <template #header>
          <XmBadge variant="info">Live</XmBadge>
        </template>
        <VChart :option="navChartOption" style="height: 280px" autoresize />
      </XmCard>

      <!-- Quick Stats -->
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
            <span class="text-sm font-mono" :class="execStore.marketStatus?.US?.is_open ? 'text-profit' : 'text-xm-text-tertiary'">
              {{ execStore.marketStatus?.US?.is_open ? 'Open' : 'Closed' }}
            </span>
          </div>
          <div class="flex justify-between items-center py-2 border-b border-xm-border-light">
            <span class="text-sm text-xm-text-secondary">HK Market</span>
            <span class="text-sm font-mono" :class="execStore.marketStatus?.HK?.is_open ? 'text-profit' : 'text-xm-text-tertiary'">
              {{ execStore.marketStatus?.HK?.is_open ? 'Open' : 'Closed' }}
            </span>
          </div>
          <div class="flex justify-between items-center py-2">
            <span class="text-sm text-xm-text-secondary">Auto Trader</span>
            <span class="text-sm font-mono text-profit font-semibold">Running</span>
          </div>
        </div>
      </XmCard>
    </div>

    <!-- Recent Positions -->
    <XmCard title="Recent Positions" class="!p-5">
      <table class="xm-table" v-if="portfolioStore.positions && portfolioStore.positions.length > 0">
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
            <td class="text-right font-mono">${{ pos.market_value?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}</td>
            <td class="text-right font-mono" :class="(pos.unrealized_pnl ?? 0) >= 0 ? 'xm-pnl-positive' : 'xm-pnl-negative'">
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
