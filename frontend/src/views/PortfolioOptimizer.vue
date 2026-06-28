<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import XmCard from '@/components/ui/XmCard.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import { usePortfolioStore } from '@/stores/usePortfolioStore'
import { tradeApi, type TradePortfolioDetail } from '@/api/tradeApi'

use([ScatterChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const portfolioStore = usePortfolioStore()

interface HoldingRow {
  ticker: string
  name: string
  shares: number
  price: number
  value: number
  weight: number
  dailyChange: number
  dailyChangePct: number
}

const holdings = ref<HoldingRow[]>([])
const portfolioMetrics = ref({
  totalValue: 0,
  totalPnl: 0,
  cash: 0,
})

const loading = ref(true)

onMounted(async () => {
  await Promise.all([
    fetchPositionsAndPortfolio(),
  ])
})

/** Fetch positions and portfolio from /api/trade/portfolio endpoint */
async function fetchPositionsAndPortfolio(): Promise<void> {
  loading.value = true
  try {
    const portfolio = await tradeApi.getPortfolio()
    const positions: TradePortfolioDetail[] = portfolio.positions ?? []
    const metrics = portfolio.metrics ?? ({} as Record<string, unknown>)

    const totalValue = (metrics.total_value as number) ?? positions.reduce((s, p) => s + (p.market_value ?? 0), 0)

    portfolioMetrics.value = {
      totalValue,
      totalPnl: (metrics.total_pnl as number) ?? 0,
      cash: (metrics.cash as number) ?? 0,
    }

    if (positions.length > 0) {
      holdings.value = positions.map((p) => {
        const weight = totalValue > 0 ? (p.market_value ?? 0) / totalValue : 0
        return {
          ticker: p.ticker,
          name: p.ticker, // name not provided by trade API; use ticker as display name
          shares: p.shares,
          price: p.current_price ?? p.avg_cost ?? 0,
          value: p.market_value ?? 0,
          weight,
          dailyChange: p.unrealized_pnl ?? 0,
          dailyChangePct: p.unrealized_pnl_pct ?? 0,
        }
      })
    }
  } catch {
    // Silent degradation — leave holdings empty
  } finally {
    loading.value = false
  }
}

const totalValue = computed(() => portfolioMetrics.value.totalValue)
const totalDailyPnL = computed(() => holdings.value.reduce((s, h) => s + h.dailyChange, 0))

// ── Efficient Frontier (placeholder — needs optimizer API support) ──
const frontierPoints = ref<Array<[number, number]>>([])
const currentPoint = ref<[number, number]>([0.15, 0.12])

/** Generate placeholder frontier points. Replace with real optimizer API when available. */
function generateFrontier(): void {
  const pts: Array<[number, number]> = []
  for (let i = 0; i < 50; i++) {
    const risk = 0.08 + (i / 50) * 0.18
    const ret = 0.06 + risk * 0.5 - Math.pow(risk - 0.13, 2) * 2 + Math.random() * 0.01
    pts.push([parseFloat(risk.toFixed(4)), parseFloat(ret.toFixed(4))])
  }
  frontierPoints.value = pts
  currentPoint.value = [0.146, 0.121]
}
generateFrontier()

const frontierOption = computed(() => ({
  grid: { top: 16, right: 24, bottom: 8, left: 60 },
  tooltip: {
    trigger: 'item' as const,
    backgroundColor: '#fff',
    borderColor: '#EEEEEE',
    textStyle: { color: '#1A1A1A', fontSize: 12 },
    formatter: (p: any) => `Risk: ${(p.value[0] * 100).toFixed(2)}%<br/>Return: ${(p.value[1] * 100).toFixed(2)}%`,
  },
  xAxis: {
    type: 'value' as const,
    name: 'Risk (Volatility)',
    nameTextStyle: { fontSize: 10, color: '#999999' },
    axisLabel: { fontSize: 10, color: '#999999', formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
    splitLine: { lineStyle: { color: '#F5F5F5' } },
  },
  yAxis: {
    type: 'value' as const,
    name: 'Return',
    nameTextStyle: { fontSize: 10, color: '#999999' },
    axisLabel: { fontSize: 10, color: '#999999', formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
    splitLine: { lineStyle: { color: '#F5F5F5' } },
  },
  series: [
    {
      type: 'scatter',
      name: 'Portfolios',
      data: frontierPoints.value,
      symbolSize: 6,
      itemStyle: { color: '#E0E0E0' },
    },
    {
      type: 'scatter',
      name: 'Current',
      data: [{
        value: currentPoint.value,
        symbolSize: 16,
        itemStyle: { color: '#FF6700', borderColor: '#fff', borderWidth: 2 },
      }],
    },
  ],
}))
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <!-- Summary Row — real portfolio metrics from API -->
    <div class="grid grid-cols-1 sm:grid-cols-4 gap-4">
      <XmCard class="!p-4">
        <div class="xm-metric-label">Total Value</div>
        <div class="xm-metric-value text-lg">${{ totalValue.toLocaleString() }}</div>
      </XmCard>
      <XmCard class="!p-4">
        <div class="xm-metric-label">Holdings</div>
        <div class="xm-metric-value text-lg">{{ holdings.length }}</div>
      </XmCard>
      <XmCard class="!p-4">
        <div class="xm-metric-label">Cash</div>
        <div class="xm-metric-value text-lg">${{ portfolioMetrics.cash.toLocaleString() }}</div>
      </XmCard>
      <XmCard class="!p-4">
        <div class="xm-metric-label">Total P&L</div>
        <div class="xm-metric-value text-lg" :class="portfolioMetrics.totalPnl >= 0 ? 'xm-pnl-positive' : 'xm-pnl-negative'">
          {{ portfolioMetrics.totalPnl >= 0 ? '+' : '' }}${{ portfolioMetrics.totalPnl.toLocaleString() }}
        </div>
      </XmCard>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="text-center py-6 text-xm-text-tertiary text-sm">
      Loading portfolio data...
    </div>

    <!-- Efficient Frontier -->
    <XmCard v-else title="Efficient Frontier">
      <template #subtitle>
        <span class="text-xs text-xm-text-tertiary">⚠ Placeholder — requires optimizer API support for real computation</span>
      </template>
      <VChart :option="frontierOption" style="height: 380px" autoresize />
    </XmCard>

    <!-- Holdings Table — real positions from API -->
    <XmCard v-if="!loading" title="Holdings" subtitle="Color-coded: green = gain, red = loss">
      <table class="xm-table" v-if="holdings.length > 0">
        <thead>
          <tr>
            <th>Ticker</th>
            <th class="text-right">Shares</th>
            <th class="text-right">Price</th>
            <th class="text-right">Value</th>
            <th class="text-right">Weight</th>
            <th class="text-right">P&L</th>
            <th class="text-right">P&L %</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="h in holdings" :key="h.ticker">
            <td class="font-mono font-semibold">{{ h.ticker }}</td>
            <td class="text-right font-mono">{{ h.shares.toFixed(0) }}</td>
            <td class="text-right font-mono">${{ h.price.toFixed(2) }}</td>
            <td class="text-right font-mono font-semibold">${{ h.value.toLocaleString() }}</td>
            <td class="text-right font-mono">{{ (h.weight * 100).toFixed(1) }}%</td>
            <td class="text-right font-mono" :class="h.dailyChange >= 0 ? 'xm-pnl-positive' : 'xm-pnl-negative'">
              {{ h.dailyChange >= 0 ? '+' : '' }}${{ Math.abs(h.dailyChange).toFixed(2) }}
            </td>
            <td class="text-right font-mono">
              <span class="xm-badge" :class="h.dailyChangePct >= 0 ? 'xm-badge-success' : 'xm-badge-danger'">
                {{ h.dailyChangePct >= 0 ? '+' : '' }}{{ h.dailyChangePct.toFixed(2) }}%
              </span>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="text-center py-10 text-xm-text-tertiary text-sm">
        No holdings data available. Ensure positions exist in your portfolio.
      </div>
    </XmCard>
  </div>
</template>
