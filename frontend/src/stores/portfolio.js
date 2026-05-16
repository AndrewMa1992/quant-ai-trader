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
  const signalHistory = reactive({})
  const trades = ref([])
  const positionDetails = ref([])
  const analysisLoading = ref(false)
  const lastAnalysisTime = ref('')

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

  async function runAnalysis(tickers = null) {
    analysisLoading.value = true
    try {
      const res = await axios.post('/api/analysis/run-analysis', { tickers })
      if (res.data.signals) {
        updateSignals(res.data.signals)
      }
      if (res.data.timestamp) {
        lastAnalysisTime.value = res.data.timestamp
      }
      // 同步获取历史
      await fetchSignalHistory()
      return res.data
    } catch (e) {
      console.error('Failed to run analysis:', e)
      return null
    } finally {
      analysisLoading.value = false
    }
  }

  async function fetchLatestSignals() {
    try {
      const res = await axios.get('/api/analysis/latest-signals')
      if (res.data.signals) {
        updateSignals(res.data.signals)
      }
    } catch (e) {
      console.error('Failed to fetch latest signals:', e)
    }
  }

  async function fetchSignalHistory(ticker = null) {
    try {
      const params = {}
      if (ticker) params.ticker = ticker
      const res = await axios.get('/api/analysis/signal-history', { params })
      if (ticker) {
        signalHistory[ticker] = res.data.history || []
      } else if (typeof res.data === 'object') {
        // 返回的是 { ticker: [entries] } 格式
        Object.keys(res.data).forEach(k => delete signalHistory[k])
        Object.assign(signalHistory, res.data)
      }
    } catch (e) {
      console.error('Failed to fetch signal history:', e)
    }
  }

  return {
    metrics,
    signals,
    signalHistory,
    trades,
    positionDetails,
    analysisLoading,
    lastAnalysisTime,
    fetchPortfolio,
    updateMetrics,
    updateSignals,
    fetchTrades,
    runAnalysis,
    fetchLatestSignals,
    fetchSignalHistory,
  }
})
