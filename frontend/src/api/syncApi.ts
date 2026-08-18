/** api/syncApi.ts – Data explorer + storage status (v2 data/execution endpoints) */
import apiClient from './index'
import { executionApi } from './executionApi'

export interface OrderRecord {
  order_id?: string
  orderId?: string
  ticker: string
  side: string
  quantity: number
  price?: number
  status: string
  order_type?: string
  created_at?: string
  updated_at?: string
  timestamp?: string
  strategy?: string
}

export interface StorageStats {
  ticker_count?: number
  total_rows?: number
  disk_usage_mb?: number
  markets?: Record<string, number>
  [key: string]: unknown
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
  /** Orders — prefer execution service; fall back to empty list */
  async getOrders(params?: { ticker?: string; status?: string; limit?: number }) {
    try {
      const data = await executionApi.getTradeLogs()
      const orders = (data?.orders ?? data ?? []) as OrderRecord[]
      let filtered = Array.isArray(orders) ? orders : []
      if (params?.ticker) {
        const t = params.ticker.toUpperCase()
        filtered = filtered.filter((o) => String(o.ticker || '').toUpperCase() === t)
      }
      if (params?.status) {
        const s = params.status.toLowerCase()
        filtered = filtered.filter((o) => String(o.status || '').toLowerCase() === s)
      }
      if (params?.limit) filtered = filtered.slice(0, params.limit)
      return { orders: filtered }
    } catch {
      return { orders: [] as OrderRecord[] }
    }
  },

  async getStoredTickers(): Promise<string[]> {
    const { data } = await apiClient.get('/v2/data/stored-tickers')
    const payload = data.data ?? data
    return payload.tickers ?? payload ?? []
  },

  async getStorageStats(): Promise<StorageStats> {
    const { data } = await apiClient.get('/v2/data/storage-stats')
    return data.data ?? data ?? {}
  },

  async getUniverse(market = 'US') {
    const { data } = await apiClient.get('/v2/data/universe', { params: { market } })
    return data.data ?? data
  },

  async getTickerInfo(ticker: string) {
    const { data } = await apiClient.get('/v2/data/ticker_info', { params: { ticker } })
    return data.data ?? data
  },

  async getBars(ticker: string, start?: string, end?: string) {
    const { data } = await apiClient.get('/v2/data/bars', {
      params: { ticker, start_date: start, end_date: end },
    })
    return data.data ?? data
  },

  async getQuote(ticker: string) {
    const { data } = await apiClient.get(`/v2/data/quote/${ticker}`)
    return data.data ?? data
  },

  async getMarketStatus() {
    const { data } = await apiClient.get('/v2/data/market_status')
    return data.data ?? data
  },

  async triggerIngest(tickers: string[], market = 'US') {
    const { data } = await apiClient.post('/v2/data/ingest', { tickers, market })
    return data.data ?? data
  },

  /** Aggregate "sync" status from storage + market status (no legacy /sync service). */
  async getSyncStatus(): Promise<{ sync_status: SyncStatusRecord[]; storage?: StorageStats }> {
    const [storage, market, tickers] = await Promise.all([
      this.getStorageStats().catch(() => ({}) as StorageStats),
      this.getMarketStatus().catch(() => ({})),
      this.getStoredTickers().catch(() => [] as string[]),
    ])
    const sync_status: SyncStatusRecord[] = [
      {
        sync_type: 'ohlcv_parquet',
        status: (tickers?.length ?? 0) > 0 ? 'ok' : 'empty',
        record_count: tickers?.length ?? storage.ticker_count ?? 0,
        last_sync_at: new Date().toISOString(),
      },
      {
        sync_type: 'market_hours',
        status: 'ok',
        last_sync_at: new Date().toISOString(),
        error_message: JSON.stringify(market ?? {}),
      },
    ]
    return { sync_status, storage }
  },

  async triggerSync(force = false) {
    // Kick a light US universe ingest as the "sync" action
    const uni = await this.getUniverse('US').catch(() => ({ tickers: ['AAPL', 'MSFT', 'SPY'] }))
    const tickers = (uni.tickers ?? uni ?? ['AAPL', 'MSFT', 'SPY']).slice(0, force ? 50 : 20)
    return this.triggerIngest(Array.isArray(tickers) ? tickers : ['AAPL', 'MSFT', 'SPY'], 'US')
  },
}
