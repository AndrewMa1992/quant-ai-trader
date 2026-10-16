/** api/riskApi.ts – /api/v2/risk/* endpoints */
import apiClient from './index'

const BASE = '/v2/risk'

export const riskApi = {
  async getBarraExposure(ticker: string) {
    const { data } = await apiClient.get(`${BASE}/barra/exposure`, { params: { ticker } })
    return data.data
  },

  async getCovariance(tickers: string) {
    const { data } = await apiClient.get(`${BASE}/barra/covariance`, { params: { tickers } })
    return data.data
  },

  async getVaR(tickers: string, weights: string, confidence = 0.95, method = 'parametric') {
    const { data } = await apiClient.get(`${BASE}/var`, {
      params: { tickers, weights, confidence, method },
    })
    return data.data
  },

  async getCVaR(tickers: string, weights: string, confidence = 0.95) {
    const { data } = await apiClient.get(`${BASE}/cvar`, {
      params: { tickers, weights, confidence },
    })
    return data.data
  },

  async getDrawdown(ticker: string) {
    const { data } = await apiClient.get(`${BASE}/drawdown`, { params: { ticker } })
    return data.data
  },

  async runStressTest(scenario: string, tickers: string[], weights?: number[]) {
    const { data } = await apiClient.post(`${BASE}/stress_test`, {
      scenario,
      tickers,
      weights,
    })
    return data.data
  },

  async getAttribution(tickers: string, weights: string, benchmark = 'SPY') {
    const { data } = await apiClient.get(`${BASE}/attribution`, {
      params: { tickers, weights, benchmark },
    })
    return data.data
  },

  // P0-2: Circuit breaker status
  async getCircuitBreakerStatus() {
    const { data } = await apiClient.get(`${BASE}/circuit_breaker`)
    return data
  },

  // P0-3: Reset circuit breaker (force reset + calibrate peak)
  async resetCircuitBreaker() {
    const { data } = await apiClient.post(`${BASE}/circuit_breaker/reset`)
    return data
  },

  // P0-3: Toggle breaker mode (hard / warn)
  async toggleBreakerMode(mode: string) {
    const { data } = await apiClient.post(`${BASE}/circuit_breaker/toggle`, { mode })
    return data
  },

  /** GET /api/v2/risk/drawdown-history — full drawdown timeline */
  async getDrawdownHistory(): Promise<{ drawdown_history: Array<{ date: string; drawdown: number }> }> {
    const { data } = await apiClient.get(`${BASE}/drawdown-history`)
    const payload = data?.data ?? data ?? {}
    const series = payload.drawdown_history ?? payload.drawdown_series ?? []
    return { drawdown_history: Array.isArray(series) ? series : [] }
  },
}
