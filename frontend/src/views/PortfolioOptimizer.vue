<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import XmCard from '@/components/ui/XmCard.vue'
import EfficientFrontier from '@/components/portfolio/EfficientFrontier.vue'
import { usePortfolioStore } from '@/stores/usePortfolioStore'
import { tradeApi, type TradePortfolioDetail } from '@/api/tradeApi'

const portfolioStore = usePortfolioStore()

interface HoldingRow {
  ticker: string
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
const optimizing = ref(false)
const optError = ref('')

const method = ref<'markowitz' | 'black_litterman' | 'risk_parity'>('markowitz')
const tickersInput = ref('AAPL,MSFT,GOOGL,SPY')
const weightRows = ref<Array<{ ticker: string; weight: number }>>([])

const frontierPoints = ref<Array<{ risk: number; return_: number; type: string }>>([])
const currentPoint = ref<{ risk: number; return_: number } | undefined>(undefined)

onMounted(async () => {
  await fetchPositionsAndPortfolio()
})

async function fetchPositionsAndPortfolio(): Promise<void> {
  loading.value = true
  try {
    await portfolioStore.fetchPositions().catch(() => {})

    if (portfolioStore.positions.length > 0) {
      const totalValue = portfolioStore.totalValue
        || portfolioStore.positions.reduce((s, p) => s + (p.market_value ?? 0), 0)
      portfolioMetrics.value = {
        totalValue,
        totalPnl: portfolioStore.totalPnl,
        cash: Number(portfolioStore.summary?.cash ?? 0),
      }
      holdings.value = portfolioStore.positions.map((p) => ({
        ticker: p.ticker,
        shares: p.quantity,
        price: p.quantity ? (p.market_value ?? 0) / p.quantity : 0,
        value: p.market_value ?? 0,
        weight: totalValue > 0 ? (p.market_value ?? 0) / totalValue : 0,
        dailyChange: p.unrealized_pnl ?? 0,
        dailyChangePct: p.cost_basis > 0
          ? ((p.unrealized_pnl ?? 0) / (p.cost_basis * Math.abs(p.quantity || 1))) * 100
          : 0,
      }))
      if (holdings.value.length > 0) {
        tickersInput.value = holdings.value.map((h) => h.ticker).join(',')
      }
      return
    }

    const portfolio = await tradeApi.getPortfolio()
    const positions: TradePortfolioDetail[] = portfolio.positions ?? []
    const metrics = portfolio.metrics ?? {}
    const totalValue = Number(metrics.total_value ?? metrics.total_market_value ?? 0)
      || positions.reduce((s, p) => s + (p.market_value ?? 0), 0)

    portfolioMetrics.value = {
      totalValue,
      totalPnl: Number(metrics.total_pnl ?? 0),
      cash: Number(metrics.cash ?? 0),
    }

    holdings.value = positions.map((p) => {
      const weight = totalValue > 0 ? (p.market_value ?? 0) / totalValue : 0
      return {
        ticker: p.ticker,
        shares: p.shares,
        price: p.current_price ?? p.avg_cost ?? 0,
        value: p.market_value ?? 0,
        weight,
        dailyChange: p.unrealized_pnl ?? 0,
        dailyChangePct: p.unrealized_pnl_pct ?? 0,
      }
    })
    if (holdings.value.length > 0) {
      tickersInput.value = holdings.value.map((h) => h.ticker).join(',')
    }
  } catch {
    holdings.value = []
  } finally {
    loading.value = false
  }
}

const totalValue = computed(() => portfolioMetrics.value.totalValue)

async function runOptimize(): Promise<void> {
  optError.value = ''
  optimizing.value = true
  weightRows.value = []
  frontierPoints.value = []
  currentPoint.value = undefined

  const tickers = tickersInput.value
    .split(',')
    .map((t) => t.trim().toUpperCase())
    .filter(Boolean)

  if (tickers.length === 0) {
    optError.value = 'Enter at least one ticker'
    optimizing.value = false
    return
  }

  try {
    if (method.value === 'markowitz') {
      await portfolioStore.optimize('max_sharpe', tickers)
    } else if (method.value === 'black_litterman') {
      await portfolioStore.optimizeBL(tickers)
    } else {
      await portfolioStore.optimizeRiskParity(tickers)
    }

    const result = portfolioStore.optimizeResult
    if (!result) {
      optError.value = portfolioStore.error || 'Optimization returned no result'
      return
    }

    const weights = result.weights ?? {}
    weightRows.value = Object.entries(weights)
      .map(([ticker, weight]) => ({ ticker, weight: Number(weight) }))
      .sort((a, b) => b.weight - a.weight)

    const risk = Number(result.expected_volatility_annual ?? 0)
    const ret = Number(result.expected_return_annual ?? 0)

    frontierPoints.value = [{
      risk: risk || 0.1,
      return_: ret || 0.08,
      type: 'frontier',
    }]

    if (holdings.value.length > 0) {
      const avgVol = risk || 0.12
      const holdRet = holdings.value.reduce((s, h) => s + h.dailyChangePct * h.weight, 0) / 100
      currentPoint.value = {
        risk: avgVol * 1.05,
        return_: Number.isFinite(holdRet) ? holdRet * 252 : ret * 0.85,
      }
    } else if (risk || ret) {
      currentPoint.value = { risk: risk * 1.1 || 0.15, return_: ret * 0.9 || 0.06 }
    }
  } catch (e: unknown) {
    optError.value = e instanceof Error ? e.message : 'Optimization failed'
  } finally {
    optimizing.value = false
  }
}

const optMetrics = computed(() => {
  const r = portfolioStore.optimizeResult
  if (!r) return null
  return {
    method: r.method,
    expectedReturn: r.expected_return_annual,
    volatility: r.expected_volatility_annual,
    sharpe: r.sharpe_ratio,
  }
})
</script>

<template>
  <div class="space-y-6 xm-fade-in">
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
        <div
          class="xm-metric-value text-lg"
          :class="portfolioMetrics.totalPnl >= 0 ? 'xm-pnl-positive' : 'xm-pnl-negative'"
        >
          {{ portfolioMetrics.totalPnl >= 0 ? '+' : '' }}${{ portfolioMetrics.totalPnl.toLocaleString() }}
        </div>
      </XmCard>
    </div>

    <XmCard title="Portfolio Optimizer" class="!p-5">
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
        <div>
          <label class="block text-xxs text-xm-text-tertiary mb-1">Method</label>
          <select v-model="method" class="xm-input w-full" :disabled="optimizing">
            <option value="markowitz">Markowitz</option>
            <option value="black_litterman">Black-Litterman</option>
            <option value="risk_parity">Risk Parity</option>
          </select>
        </div>
        <div class="sm:col-span-2">
          <label class="block text-xxs text-xm-text-tertiary mb-1">Tickers</label>
          <input
            v-model="tickersInput"
            class="xm-input w-full"
            placeholder="AAPL,MSFT,GOOGL,SPY"
            :disabled="optimizing"
          />
        </div>
      </div>
      <div class="flex items-center gap-3">
        <button class="xm-btn-primary" :disabled="optimizing" @click="runOptimize">
          {{ optimizing ? 'Optimizing...' : 'Run Optimize' }}
        </button>
        <span v-if="optError" class="text-sm text-loss">{{ optError }}</span>
      </div>

      <div v-if="optMetrics" class="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
        <div class="p-3 rounded-lg bg-xm-bg-surface">
          <div class="xm-metric-label">Method</div>
          <div class="text-sm font-mono font-semibold mt-1">{{ optMetrics.method }}</div>
        </div>
        <div class="p-3 rounded-lg bg-xm-bg-surface">
          <div class="xm-metric-label">Expected Return</div>
          <div class="text-sm font-mono font-semibold mt-1">
            {{ optMetrics.expectedReturn != null ? (optMetrics.expectedReturn * 100).toFixed(2) + '%' : '—' }}
          </div>
        </div>
        <div class="p-3 rounded-lg bg-xm-bg-surface">
          <div class="xm-metric-label">Volatility</div>
          <div class="text-sm font-mono font-semibold mt-1">
            {{ optMetrics.volatility != null ? (optMetrics.volatility * 100).toFixed(2) + '%' : '—' }}
          </div>
        </div>
        <div class="p-3 rounded-lg bg-xm-bg-surface">
          <div class="xm-metric-label">Sharpe</div>
          <div class="text-sm font-mono font-semibold mt-1">
            {{ optMetrics.sharpe != null ? optMetrics.sharpe.toFixed(2) : '—' }}
          </div>
        </div>
      </div>
    </XmCard>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <XmCard title="Optimized Weights">
        <table v-if="weightRows.length > 0" class="xm-table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th class="text-right">Weight</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in weightRows" :key="row.ticker">
              <td class="font-mono font-semibold">{{ row.ticker }}</td>
              <td class="text-right font-mono">{{ (row.weight * 100).toFixed(2) }}%</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="text-center py-10 text-xm-text-tertiary text-sm">
          Run optimize to see target weights.
        </div>
      </XmCard>

      <XmCard title="Risk / Return">
        <EfficientFrontier
          v-if="frontierPoints.length > 0"
          :points="frontierPoints"
          :current="currentPoint"
        />
        <div v-else class="text-center py-10 text-xm-text-tertiary text-sm">
          Optimize to plot expected return vs volatility.
        </div>
      </XmCard>
    </div>

    <div v-if="loading" class="text-center py-6 text-xm-text-tertiary text-sm">
      Loading portfolio data...
    </div>

    <XmCard v-else title="Holdings" subtitle="Current positions">
      <table v-if="holdings.length > 0" class="xm-table">
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
            <td
              class="text-right font-mono"
              :class="h.dailyChange >= 0 ? 'xm-pnl-positive' : 'xm-pnl-negative'"
            >
              {{ h.dailyChange >= 0 ? '+' : '' }}${{ Math.abs(h.dailyChange).toFixed(2) }}
            </td>
            <td class="text-right font-mono">
              <span
                class="xm-badge"
                :class="h.dailyChangePct >= 0 ? 'xm-badge-success' : 'xm-badge-danger'"
              >
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
