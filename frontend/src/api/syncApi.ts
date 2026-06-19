/** api/syncApi.ts – Phase 5: Data & Sync endpoints */
import apiClient from './index'

export interface OrderRecord {
  order_id: string
  ticker: string
  side: string
  quantity: number
  price?: number
  status: string
  order_type?: string
  created_at?: string
  updated_at?: string
}

export interface TransactionRecord {
  transaction_id: string
  order_id?: string
  ticker: string
  side: string
  quantity: number
  price: number
  value?: number
  timestamp?: string
}

export interface FundamentalRecord {
  ticker: string
  pe_ratio?: number
  pb_ratio?: number
  eps?: number
  dividend_yield?: number
  beta?: number
  market_cap?: number
  sector?: string
  industry?: string
  updated_at?: string
}

export interface CapitalFlowRecord {
  date?: string
  ticker: string
  net_inflow?: number
  main_inflow?: number
  main_outflow?: number
  super_large_inflow?: number
  super_large_outflow?: number
  large_inflow?: number
  large_outflow?: number
}

export interface CalendarRecord {
  date: string
  market: string
  is_trading_day: boolean
  open_time?: string
  close_time?: string
  holiday_name?: string
}

export interface SyncStatusRecord {
  sync_type: string
  last_sync_at?: string
  last_success_at?: string
  status: string
  record_count?: number
  error_message?: string
}

export const syncApi = {
  async getOrders(params?: { ticker?: string; status?: string; limit?: number }) {
    const { data } = await apiClient.get('/data/orders', { params })
    return data.data
  },
  async getTransactions(params?: { ticker?: string; order_id?: string; since?: string; limit?: number }) {
    const { data } = await apiClient.get('/data/transactions', { params })
    return data.data
  },
  async getFundamentals(ticker: string): Promise<FundamentalRecord> {
    const { data } = await apiClient.get(`/data/fundamentals/${ticker}`)
    return data.data
  },
  async getCapitalFlow(ticker: string, params?: { start_date?: string; end_date?: string; limit?: number }) {
    const { data } = await apiClient.get(`/data/capital-flow/${ticker}`, { params })
    return data.data
  },
  async getCalendar(params?: { market?: string; start_date?: string; end_date?: string; trading_only?: boolean }) {
    const { data } = await apiClient.get('/data/calendar', { params })
    return data.data
  },
  async getSyncStatus(): Promise<{ sync_status: SyncStatusRecord[]; rate_limiter?: any }> {
    const { data } = await apiClient.get('/sync/status')
    return data.data
  },
  async triggerSync(force = false) {
    const { data } = await apiClient.get('/sync/start', { params: { force } })
    return data.data
  },
  async getDataSyncStatus() {
    const { data } = await apiClient.get('/data/sync-status')
    return data.data
  },
}
