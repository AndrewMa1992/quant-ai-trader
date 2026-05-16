import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export const useMarketStore = defineStore('market', () => {
  const ticks = ref([])
  const priceHistory = ref({})
  const usTickers = ref([])
  const hkTickers = ref([])
  const loading = ref(false)
  const allTickers = computed(() => [...usTickers.value, ...hkTickers.value.map(t => t + '.HK')])

  function updateTicks(newTicks) {
    ticks.value = newTicks
    for (const tick of newTicks) {
      const key = tick.display || tick.ticker
      if (!priceHistory.value[key]) {
        priceHistory.value[key] = []
      }
      priceHistory.value[key].push({
        time: tick.timestamp,
        price: tick.price,
        market: tick.market,
      })
      if (priceHistory.value[key].length > 200) {
        priceHistory.value[key] = priceHistory.value[key].slice(-200)
      }
    }
  }

  async function fetchTickers() {
    try {
      const res = await axios.get('/api/data/tickers')
      usTickers.value = res.data.us_tickers || []
      hkTickers.value = res.data.hk_tickers || []
    } catch (e) {
      console.error('Failed to fetch tickers:', e)
    }
  }

  async function fetchHistory(ticker, period = '1mo', interval = '1d') {
    loading.value = true
    try {
      const res = await axios.get('/api/data/history/' + ticker, {
        params: { period, interval, include_features: false }
      })
      return res.data
    } catch (e) {
      console.error('Failed to fetch history:', e)
      return null
    } finally {
      loading.value = false
    }
  }

  function getPriceHistory(ticker) {
    return priceHistory.value[ticker] || []
  }

  return {
    ticks, priceHistory, usTickers, hkTickers, loading, allTickers,
    updateTicks, fetchTickers, fetchHistory, getPriceHistory,
  }
})
