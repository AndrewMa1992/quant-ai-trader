/** api/dataApi.ts – /api/v2/data/* endpoints */
import apiClient from './index'

const BASE = '/v2/data'

export interface TickerInfo {
  ticker: string
  name?: string
  sector?: string
  market?: string
  industry?: string
  currency?: string
  exchange?: string
}

export interface OHLCBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  adj_close?: number
  volume: number
}

export interface MarketStatus {
  [market: string]: {
    is_open: boolean
    seconds_to_open: number
    seconds_to_close: number
  }
}

export const dataApi = {
  async getBars(ticker: string, start: string, end?: string) {
    const { data } = await apiClient.get(`${BASE}/bars`, {
      params: { ticker, start_date: start, end_date: end },
    })
    return data.data
  },

  async getMinuteBars(ticker: string, dateStr: string) {
    const { data } = await apiClient.get(`${BASE}/minute_bars`, {
      params: { ticker, date_str: dateStr },
    })
    return data.data
  },

  async getTickerInfo(ticker: string): Promise<TickerInfo> {
    const { data } = await apiClient.get(`${BASE}/ticker_info`, { params: { ticker } })
    return data.data
  },

  async getUniverse(market?: string, sector?: string) {
    const { data } = await apiClient.get(`${BASE}/universe`, { params: { market, sector } })
    return data.data
  },

  async getMarketStatus(): Promise<MarketStatus> {
    const { data } = await apiClient.get(`${BASE}/market_status`)
    return data.data
  },

  async ingest(tickers: string[], startDate?: string, endDate?: string) {
    const { data } = await apiClient.post(`${BASE}/ingest`, {
      tickers,
      start_date: startDate,
      end_date: endDate,
    })
    return data.data
  },

  // Dashboard summary
  async getDashboard() {
    const { data } = await apiClient.get(`${BASE}/dashboard`)
    return data.data
  },
}
