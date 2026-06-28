/** api/tradeApi.ts – /api/trade/* and /api/v2/analysis/* endpoints */
import apiClient from './index'

// ── Types ────────────────────────────────────────────────────

export interface TradeRecord {
  id: number
  ticker: string
  side: string
  quantity: number
  price: number
  value: number
  commission?: number
  timestamp: string
  signal_strength?: number | null
  strategy?: string | null
  status: string
}

export interface TradePosition {
  ticker: string
  shares: number
}

export interface TradePortfolioDetail {
  ticker: string
  shares: number
  avg_cost: number
  current_price: number
  current_price_usd: number
  currency: string
  market_value: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  allocation: number
}

export interface TradePortfolio {
  metrics: Record<string, unknown>
  positions: TradePortfolioDetail[]
  value_history: Array<{ time: string; value: number }>
  tiger_synced?: boolean
  tiger_data?: unknown
}

export interface PortfolioHistoryPoint {
  date: string
  nav: number
  cumulative_return: number
  drawdown_from_peak: number
}

// ── API Functions ────────────────────────────────────────────

export const tradeApi = {
  /** GET /api/trade/portfolio — full portfolio state with value_history */
  async getPortfolio(): Promise<TradePortfolio> {
    const { data } = await apiClient.get('/trade/portfolio')
    return data
  },

  /** GET /api/trade/positions — position list + cash */
  async getPositions(): Promise<{ positions: TradePosition[]; cash: number }> {
    const { data } = await apiClient.get('/trade/positions')
    return data
  },

  /** GET /api/trade/history — trade log history */
  async getTradeHistory(limit = 50): Promise<{ trades: TradeRecord[] }> {
    const { data } = await apiClient.get('/trade/history', { params: { limit } })
    return data
  },

  /** GET /api/v2/analysis/portfolio-history — NAV history with returns & drawdown */
  async getPortfolioHistory(days = 90): Promise<{ history: PortfolioHistoryPoint[] }> {
    const { data } = await apiClient.get('/v2/analysis/portfolio-history', { params: { days } })
    return data
  },

  /** GET /api/trade/dashboard — real-time dashboard metrics with Sharpe, max DD, win rate */
  async getDashboard(): Promise<DashboardData> {
    const { data } = await apiClient.get('/trade/dashboard')
    return data
  },
}

/** Dashboard metrics from GET /api/trade/dashboard */
export interface DashboardData {
  total_value?: number
  cash?: number
  positions_value?: number
  total_pnl?: number
  total_return_pct?: number
  sharpe_ratio?: number
  max_drawdown?: number
  max_drawdown_pct?: number
  win_rate?: number
  profit_factor?: number
  calmar_ratio?: number
  snapshot_count?: number
  timestamp?: string
  [key: string]: unknown
}
