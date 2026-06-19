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
    const { data } = await apiClient.get('/v2/analysis/portfolio-history')
    return data.data ?? []
  },

  async getYearlyReturns(): Promise<YearlyReturn[]> {
    const { data } = await apiClient.get('/v2/analysis/yearly-returns')
    return data.data ?? []
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

  // Trade logs for ExecutionMonitor
  async getTradeLogs(date?: string) {
    const { data } = await apiClient.get(`${BASE}/trades`, { params: { date } })
    return data.data
  },
}
