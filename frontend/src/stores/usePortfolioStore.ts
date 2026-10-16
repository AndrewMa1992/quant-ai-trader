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
  const buyingPower = ref(0)
  const tigerAccount = ref('')

  const positionsWithColors = computed(() => {
    return positions.value.map(p => ({
      ...p,
      pnlColor: (p.unrealized_pnl ?? 0) >= 0 ? 'profit' as const : 'loss' as const,
      pnlPercent: p.cost_basis > 0
        ? ((p.unrealized_pnl ?? 0) / (p.cost_basis * Math.abs(p.quantity || 1))) * 100
        : 0,
    }))
  })

  const totalValue = computed(() => summary.value?.total_market_value ?? 0)
  const totalPnl = computed(() => summary.value?.total_pnl ?? 0)
  const unrealizedPnl = computed(() => summary.value?.unrealized_pnl ?? 0)
  const cash = computed(() => summary.value?.cash ?? 0)

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

    const acct = (typeof snap.account === 'object' && snap.account)
      ? snap.account as Record<string, unknown>
      : {}
    const nav = Number(snap.nav ?? snap.total_value ?? acct.nav ?? acct.net_liquidation ?? 0)
    const cashAmt = Number(snap.cash ?? acct.cash ?? 0)
    const bpAmt = Number(snap.buying_power ?? acct.buying_power ?? cashAmt)
    const pnlSum = positions.value.reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0)
    summary.value = {
      position_count: positions.value.length,
      total_market_value: nav || positions.value.reduce((s, p) => s + Math.abs(p.market_value || 0), 0) || cashAmt,
      unrealized_pnl: pnlSum,
      realized_pnl: Number(acct.realized_pnl ?? 0),
      total_pnl: pnlSum,
      cash: cashAmt,
      buying_power: bpAmt,
      source: String(snap.source || 'tiger'),
    }
    buyingPower.value = bpAmt
    const acctId = acct.account ?? snap.account
    if (acctId && typeof acctId !== 'object') {
      tigerAccount.value = String(acctId)
    }
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
      const s = data.summary
      buyingPower.value = Number(s?.buying_power ?? s?.cash ?? buyingPower.value)
      if (s?.source) liveSource.value = s.source
      lastLiveAt.value = new Date().toISOString()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Positions fetch failed'
    } finally {
      loading.value = false
    }
  }

  async function fetchTigerAccount() {
    try {
      const acct = await executionApi.getTigerAccount()
      tigerAccount.value = String(acct.account || tigerAccount.value)
      const cashAmt = Number(acct.cash ?? 0)
      const navAmt = Number(acct.nav ?? acct.net_liquidation ?? 0)
      const bpAmt = Number(acct.buying_power ?? cashAmt)
      buyingPower.value = bpAmt
      if (summary.value) {
        summary.value = {
          ...summary.value,
          cash: Number.isFinite(cashAmt) ? cashAmt : summary.value.cash,
          total_market_value: navAmt > 0 ? navAmt : summary.value.total_market_value,
          buying_power: bpAmt,
        }
      } else {
        summary.value = {
          position_count: positions.value.length,
          total_market_value: navAmt,
          unrealized_pnl: 0,
          realized_pnl: 0,
          total_pnl: 0,
          cash: cashAmt,
          buying_power: bpAmt,
          source: 'tiger',
        }
      }
      liveSource.value = 'tiger'
      lastLiveAt.value = new Date().toISOString()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Tiger account fetch failed'
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
    liveSource, lastLiveAt, buyingPower, tigerAccount,
    positionsWithColors, totalValue, totalPnl, unrealizedPnl, cash,
    fetchPositions, fetchTigerAccount, applyTigerSnapshot, optimize, optimizeBL, optimizeRiskParity, runBacktest,
  }
})
