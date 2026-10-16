/** api/executionApi.ts – /api/v2/execution/* endpoints */
import apiClient from './index'

const BASE = '/v2/execution'

export interface Position {
  ticker: string
  quantity: number
  cost_basis: number
  market_value: number
  unrealized_pnl: number
  day_trades: number
}

export interface PortfolioSummary {
  position_count: number
  total_market_value: number
  unrealized_pnl: number
  realized_pnl: number
  total_pnl: number
  cash?: number
  buying_power?: number
  source?: string
}

export interface TigerAccount {
  account?: string
  nav?: number
  cash?: number
  buying_power?: number
  currency?: string
  status?: string
  segments?: Array<Record<string, unknown>>
  sandbox?: boolean | null
  paper?: boolean
  [key: string]: unknown
}

export interface Alert {
  id: string
  message: string
  severity: string
  source: string
  timestamp: string
}

export interface OptimizeResult {
  weights: Record<string, number>
  expected_return_annual?: number
  expected_volatility_annual?: number
  sharpe_ratio?: number
  method: string
}

export interface BacktestResult {
  sharpe_ratio: number
  total_return: number
  max_drawdown: number
  final_value: number
  annual_return: number
}

// ── Analysis types ──

export interface PortfolioHistoryPoint {
  date: string
  nav: number
  benchmark: number
}

export interface YearlyReturn {
  year: string
  return: number
}

export const analysisApi = {
  async getPortfolioHistory(): Promise<PortfolioHistoryPoint[]> {
    const { data } = await apiClient.get('/v2/risk/portfolio-history')
    const payload = data?.data ?? {}
    const raw = payload.nav_history ?? payload.history ?? (Array.isArray(payload) ? payload : [])
    if (!Array.isArray(raw)) return []
    return raw
      .filter((p: { nav?: number }) => Number(p.nav) > 0)
      .map((p: { date?: string; nav?: number; benchmark?: number }) => ({
        date: String(p.date ?? ''),
        nav: Number(p.nav ?? 0),
        benchmark: Number(p.benchmark ?? p.nav ?? 0),
      }))
  },

  async getYearlyReturns(): Promise<YearlyReturn[]> {
    const year = new Date().getFullYear()
    const { data } = await apiClient.get('/v2/risk/yearly-returns', { params: { year } })
    const payload = data?.data ?? {}
    if (Array.isArray(payload)) return payload
    if (Array.isArray(payload.returns) && payload.returns.length > 0) {
      return payload.returns.map((row: { year?: string; return?: number }) => ({
        year: String(row.year ?? year),
        return: Number(row.return ?? 0),
      }))
    }
    const monthly = payload.monthly_returns ?? {}
    return Object.entries(monthly).map(([key, value]) => ({
      year: key,
      return: Number(value),
    }))
  },
}

export const executionApi = {
  // Optimizers
  async optimizeMarkowitz(tickers: string[], objective = 'max_sharpe', constraints: Record<string, unknown> = {}) {
    const { data } = await apiClient.post(`${BASE}/optimizer/markowitz`, {
      tickers, objective, constraints,
    })
    return data.data
  },

  async optimizeBlackLitterman(tickers: string[], views: { ticker?: string; return?: number; confidence?: number }[] = [], tau = 0.05) {
    const { data } = await apiClient.post(`${BASE}/optimizer/bl`, { tickers, views, tau })
    return data.data
  },

  async optimizeRiskParity(tickers: string[]) {
    const { data } = await apiClient.post(`${BASE}/optimizer/risk_parity`, { tickers })
    return data.data
  },

  // Backtest
  async runBacktest(tickers: string[], startDate: string, endDate: string, initialCapital = 1_000_000) {
    const { data } = await apiClient.post(`${BASE}/backtest`, {
      tickers, start_date: startDate, end_date: endDate, initial_capital: initialCapital,
    })
    return data.data
  },

  // Execution
  async placeOrder(ticker: string, side: string, quantity: number, orderType = 'MKT', limitPrice?: number, algo = 'twap') {
    const { data } = await apiClient.post(`${BASE}/execute/order`, {
      ticker, side, quantity, order_type: orderType, limit_price: limitPrice, algo,
    })
    return data.data
  },

  async getPositions(): Promise<{ positions: Position[]; summary: PortfolioSummary }> {
    const { data } = await apiClient.get(`${BASE}/positions`)
    return data.data
  },

  async getAlerts(severity = ''): Promise<{ alerts: Alert[] }> {
    const { data } = await apiClient.get(`${BASE}/alerts`, { params: { severity } })
    return data.data
  },

  // Trade / order logs for ExecutionMonitor
  async getTradeLogs(date?: string) {
    const { data } = await apiClient.get(`${BASE}/orders`, { params: { since: date } })
    return data.data
  },

  async getTigerAccount(): Promise<TigerAccount> {
    const { data } = await apiClient.get(`${BASE}/tiger/account`)
    return (data.data ?? data ?? {}) as TigerAccount
  },

  async getTigerSnapshot(): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get(`${BASE}/tiger/snapshot`)
    return (data.data ?? data ?? {}) as Record<string, unknown>
  },

  async syncTiger(): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post(`${BASE}/tiger/sync`)
    return (data.data ?? data ?? {}) as Record<string, unknown>
  },

  // Rollback
  async rollback(): Promise<{ success: boolean; message: string; timestamp: string }> {
    const { data } = await apiClient.post(`${BASE}/rollback`)
    return data
  },
}
