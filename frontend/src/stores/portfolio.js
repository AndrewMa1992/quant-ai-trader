import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import axios from 'axios'

export const usePortfolioStore = defineStore('portfolio', () => {
  const metrics = reactive({
    total_value: 100000,
    cash: 100000,
    positions_value: 0,
    total_pnl: 0,
    total_return_pct: 0,
    sharpe_ratio: 0,
    max_drawdown: 0,
    num_positions: 0,
    total_trades: 0,
  })

  const signals = reactive({})
  const trades = ref([])
  const positionDetails = ref([])

  async function fetchPortfolio() {
    try {
      const res = await axios.get('/api/trade/portfolio')
      if (res.data.metrics) {
        Object.assign(metrics, res.data.metrics)
      }
    } catch (e) {
      console.error('Failed to fetch portfolio:', e)
    }
  }

  function updateMetrics(newMetrics) {
    Object.assign(metrics, newMetrics)
  }

  function updateSignals(newSignals) {
    Object.keys(signals).forEach(k => delete signals[k])
    if (newSignals) {
      Object.assign(signals, newSignals)
    }
  }

  async function fetchTrades(ticker = null, limit = 100) {
    try {
      const params = { limit }
      if (ticker) params.ticker = ticker
      const res = await axios.get('/api/trade/history', { params })
      trades.value = res.data.trades || []
    } catch (e) {
      console.error('Failed to fetch trades:', e)
    }
  }

  return {
    metrics,
    signals,
    trades,
    positionDetails,
    fetchPortfolio,
    updateMetrics,
    updateSignals,
    fetchTrades,
  }
})
