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
  /** GET /api/v2/execution/positions — portfolio positions + summary */
  async getPortfolio(): Promise<TradePortfolio> {
    const { data } = await apiClient.get('/v2/execution/positions')
    const payload = data?.data ?? data ?? {}
    const positions = (payload.positions ?? []).map((p: Record<string, unknown>) => ({
      ticker: String(p.ticker ?? ''),
      shares: Number(p.quantity ?? p.shares ?? 0),
      avg_cost: Number(p.cost_basis ?? p.avg_cost ?? 0),
      current_price: Number(p.market_price ?? p.current_price ?? 0),
      current_price_usd: Number(p.market_price ?? p.current_price_usd ?? 0),
      currency: String(p.currency ?? 'USD'),
      market_value: Number(p.market_value ?? 0),
      unrealized_pnl: Number(p.unrealized_pnl ?? 0),
      unrealized_pnl_pct: Number(p.unrealized_pnl_pct ?? 0),
      allocation: Number(p.weight ?? p.allocation ?? 0),
    }))
    return {
      metrics: payload.summary ?? {},
      positions,
      value_history: payload.value_history ?? [],
    }
  },

  /** GET /api/v2/execution/positions — position list + cash */
  async getPositions(): Promise<{ positions: TradePosition[]; cash: number }> {
    const { data } = await apiClient.get('/v2/execution/positions')
    const payload = data?.data ?? data ?? {}
    return {
      positions: (payload.positions ?? []).map((p: Record<string, unknown>) => ({
        ticker: String(p.ticker ?? ''),
        shares: Number(p.quantity ?? p.shares ?? 0),
      })),
      cash: Number(payload.summary?.cash ?? payload.cash ?? 0),
    }
  },

  /** GET /api/v2/execution/orders — trade / order history */
  async getTradeHistory(limit = 50): Promise<{ trades: TradeRecord[] }> {
    const { data } = await apiClient.get('/v2/execution/orders', { params: { limit } })
    const orders = data?.data?.orders ?? data?.data ?? []
    return { trades: Array.isArray(orders) ? orders : [] }
  },

  /** GET /api/v2/risk/portfolio-history — NAV history with returns & drawdown */
  async getPortfolioHistory(days = 90): Promise<{ history: PortfolioHistoryPoint[] }> {
    const { data } = await apiClient.get('/v2/risk/portfolio-history', { params: { days } })
    const history = data?.data?.history ?? data?.history ?? data?.data ?? []
    return { history: Array.isArray(history) ? history : [] }
  },

  /** GET /api/v2/dashboard — real-time dashboard metrics with Sharpe, max DD, win rate */
  async getDashboard(): Promise<DashboardData> {
    const { data } = await apiClient.get('/v2/dashboard')
    return (data?.data ?? data) as DashboardData
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
