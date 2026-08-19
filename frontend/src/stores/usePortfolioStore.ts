/** stores/usePortfolioStore.ts – Portfolio data Pinia store v2.1 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { executionApi, type Position, type PortfolioSummary, type OptimizeResult, type BacktestResult } from '../api/executionApi'

export const usePortfolioStore = defineStore('portfolio', () => {
  const positions = ref<Position[]>([])
  const summary = ref<PortfolioSummary | null>(null)
  const optimizeResult = ref<OptimizeResult | null>(null)
  const backtestResult = ref<BacktestResult | null>(null)
  const loading = ref(false)
  const error = ref('')
  const liveSource = ref('')
  const lastLiveAt = ref('')

  // Computed: positions with color coding (green = positive PnL, red = negative)
  const positionsWithColors = computed(() => {
    return positions.value.map(p => ({
      ...p,
      pnlColor: (p.unrealized_pnl ?? 0) >= 0 ? 'profit' as const : 'loss' as const,
      pnlPercent: p.cost_basis > 0
        ? ((p.unrealized_pnl ?? 0) / (p.cost_basis * Math.abs(p.quantity || 1))) * 100
        : 0,
    }))
  })

  // Computed: total portfolio metrics
  const totalValue = computed(() => summary.value?.total_market_value ?? 0)
  const totalPnl = computed(() => summary.value?.total_pnl ?? 0)
  const unrealizedPnl = computed(() => summary.value?.unrealized_pnl ?? 0)
  const cash = computed(() => (summary.value as PortfolioSummary & { cash?: number } | null)?.cash ?? 0)

  /** Apply Tiger/local paper WS snapshot immediately (no HTTP round-trip). */
  function applyTigerSnapshot(snap: Record<string, unknown>) {
    const rawPos = (snap.positions as Array<Record<string, unknown>> | undefined) ?? []
    positions.value = rawPos.map((p) => {
      const qty = Number(p.quantity ?? p.shares ?? 0)
      const avg = Number(p.avg_cost ?? p.cost_basis ?? 0)
      const mv = Number(p.market_value ?? 0)
      const px = Number(p.market_price ?? (qty ? mv / Math.abs(qty) : 0))
      const unreal = Number(p.unrealized_pnl ?? (px - avg) * qty)
      return {
        ticker: String(p.ticker ?? ''),
        quantity: qty,
        cost_basis: avg,
        market_value: mv,
        unrealized_pnl: unreal,
        day_trades: 0,
      }
    }).filter((p) => p.ticker)

    const nav = Number(snap.nav ?? snap.total_value ?? 0)
    const cashAmt = Number(
      (snap.cash as number | undefined)
      ?? (snap.account as Record<string, unknown> | undefined)?.cash
      ?? 0,
    )
    const pnlSum = positions.value.reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0)
    summary.value = {
      position_count: positions.value.length,
      total_market_value: nav || positions.value.reduce((s, p) => s + Math.abs(p.market_value || 0), 0),
      unrealized_pnl: pnlSum,
      realized_pnl: 0,
      total_pnl: pnlSum,
      ...( { cash: cashAmt } as Partial<PortfolioSummary> ),
    } as PortfolioSummary
    liveSource.value = String(snap.source || 'tiger')
    lastLiveAt.value = String(snap.timestamp || new Date().toISOString())
  }

  async function fetchPositions() {
    loading.value = true
    error.value = ''
    try {
      const data = await executionApi.getPositions()
      positions.value = data.positions ?? []
      summary.value = data.summary
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Positions fetch failed'
    } finally {
      loading.value = false
    }
  }

  async function optimize(objective: string, tickers: string[], constraints: Record<string, unknown> = {}) {
    loading.value = true
    try {
      optimizeResult.value = await executionApi.optimizeMarkowitz(tickers, objective, constraints)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Optimization failed'
    } finally {
      loading.value = false
    }
  }

  async function optimizeBL(tickers: string[], views: { ticker?: string; return?: number; confidence?: number }[] = []) {
    loading.value = true
    try {
      optimizeResult.value = await executionApi.optimizeBlackLitterman(tickers, views)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'BL optimization failed'
    } finally {
      loading.value = false
    }
  }

  async function optimizeRiskParity(tickers: string[]) {
    loading.value = true
    try {
      optimizeResult.value = await executionApi.optimizeRiskParity(tickers)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Risk parity failed'
    } finally {
      loading.value = false
    }
  }

  async function runBacktest(tickers: string[], startDate: string, endDate: string, capital = 1_000_000) {
    loading.value = true
    try {
      backtestResult.value = await executionApi.runBacktest(tickers, startDate, endDate, capital)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Backtest failed'
    } finally {
      loading.value = false
    }
  }

  return {
    positions, summary, optimizeResult, backtestResult, loading, error,
    liveSource, lastLiveAt,
    positionsWithColors, totalValue, totalPnl, unrealizedPnl, cash,
    fetchPositions, applyTigerSnapshot, optimize, optimizeBL, optimizeRiskParity, runBacktest,
  }
})
