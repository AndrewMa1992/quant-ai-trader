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
    max_drawdown_pct: 0,
    win_rate: 0,
    profit_factor: 0,
    calmar_ratio: 0,
    num_positions: 0,
    total_trades: 0,
  })

  const signals = reactive({})
  const signalHistory = reactive({})
  const trades = ref([])
  const positionDetails = ref([])
  const valueHistory = ref([])
  const analysisLoading = ref(false)
  const lastAnalysisTime = ref('')
  const dashboardMetrics = ref({})

  async function fetchPortfolio() {
    try {
      const res = await axios.get('/api/trade/portfolio')
      if (res.data.metrics) {
        Object.assign(metrics, res.data.metrics)
      }
      if (res.data.positions) {
        positionDetails.value = res.data.positions
      }
      if (res.data.value_history) {
        valueHistory.value = res.data.value_history
      }
      return res.data
    } catch (e) {
      console.error('Failed to fetch portfolio:', e)
      return null
    }
  }

  async function fetchDashboard() {
    try {
      const res = await axios.get('/api/trade/dashboard')
      dashboardMetrics.value = res.data
      // Sync to metrics
      Object.assign(metrics, {
        sharpe_ratio: res.data.sharpe_ratio || 0,
        max_drawdown: res.data.max_drawdown || 0,
        max_drawdown_pct: res.data.max_drawdown_pct || 0,
        win_rate: res.data.win_rate || 0,
        profit_factor: res.data.profit_factor || 0,
        calmar_ratio: res.data.calmar_ratio || 0,
        total_value: res.data.total_value || metrics.total_value,
        cash: res.data.cash || metrics.cash,
        total_pnl: res.data.total_pnl || metrics.total_pnl,
        total_return_pct: res.data.total_return_pct || metrics.total_return_pct,
      })
    } catch (e) {
      console.error('Failed to fetch dashboard:', e)
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

  function prependTrades(newTrades) {
    trades.value = [...newTrades, ...trades.value].slice(0, 200)
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
    valueHistory,
    analysisLoading,
    lastAnalysisTime,
    dashboardMetrics,
    fetchPortfolio,
    fetchDashboard,
    updateMetrics,
    updateSignals,
    prependTrades,
    fetchTrades,
    runAnalysis,
    fetchLatestSignals,
    fetchSignalHistory,
  }
})
