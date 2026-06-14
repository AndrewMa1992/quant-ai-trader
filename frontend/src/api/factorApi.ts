/** api/factorApi.ts – /api/v2/factors/* endpoints */
import axios from 'axios'

const BASE = '/api/v2/factors'

export interface FactorDef {
  id: string
  name: string
  category: string
  subcategory: string
  description: string
  lookback_default: number
  frequency: string
  direction: number
}

export interface ICAnalysis {
  rank_ic_mean: number
  rank_ic_std: number
  information_ratio: number
  ic_t_stat: number
  positive_ic_ratio: number
  ic_series: { date: string; ic: number }[]
  ic_cumulative: { date: string; cumulative_ic: number }[]
  monthly_ic: { year: number; month: number; ic: number }[]
}

export const factorApi = {
  async listFactors(category?: string) {
    const { data } = await axios.get(`${BASE}/factors`, { params: { category } })
    return data.data
  },

  async getFactor(name: string) {
    const { data } = await axios.get(`${BASE}/factors/${name}`)
    return data.data
  },

  async getICAnalysis(factorName: string, window = 252): Promise<ICAnalysis> {
    const { data } = await axios.get(`${BASE}/ic-analysis`, {
      params: { factor_name: factorName, window },
    })
    return data.data
  },

  async getCorrelation(factorNames: string) {
    const { data } = await axios.get(`${BASE}/correlation`, {
      params: { factor_names: factorNames },
    })
    return data.data
  },

  async getDecay(factorName: string, maxLags = 20) {
    const { data } = await axios.get(`${BASE}/decay`, {
      params: { factor_name: factorName, max_lags: maxLags },
    })
    return data.data
  },

  async computeFactors(tickers: string[], factorNames?: string[], startDate?: string, endDate?: string) {
    const { data } = await axios.post(`${BASE}/compute`, {
      tickers,
      factor_names: factorNames ?? [],
      start_date: startDate,
      end_date: endDate,
    })
    return data.data
  },
}
