/** stores/useRiskStore.ts – Risk data Pinia store v2.1 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { riskApi } from '../api/riskApi'

export const useRiskStore = defineStore('risk', () => {
  const barraExposures = ref<Record<string, number>>({})
  const covarianceMatrix = ref<number[][]>([])
  const varData = ref<Record<string, unknown>>({})
  const cvarData = ref<Record<string, unknown>>({})
  const drawdownData = ref<Record<string, unknown>>({})
  const stressTestResult = ref<Record<string, unknown>>({})

  // P0-2: Circuit breaker state fields
  const circuitBreakerTriggered = ref(false)
  const dailyPnl = ref(0)
  const dailyPnlPct = ref(0)
  const currentDrawdown = ref(0)
  const circuitBreakerCooldown = ref(0)

  const loading = ref(false)
  const error = ref('')

  // Computed: risk level based on drawdown
  const riskLevel = computed(() => {
    if (circuitBreakerTriggered.value) return 'critical'
    if (currentDrawdown.value >= 0.15) return 'high'
    if (currentDrawdown.value >= 0.05) return 'elevated'
    return 'normal'
  })

  async function fetchBarra(ticker: string) {
    loading.value = true
    error.value = ''
    try {
      const data = await riskApi.getBarraExposure(ticker)
      barraExposures.value = data.exposures ?? {}
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Barra fetch failed'
    } finally {
      loading.value = false
    }
  }

  async function fetchVaR(tickers: string[], weights: number[], confidence = 0.95, method = 'parametric') {
    try {
      const data = await riskApi.getVaR(tickers.join(','), weights.join(','), confidence, method)
      varData.value = data
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'VaR failed'
    }
  }

  async function fetchCVaR(tickers: string[], weights: number[], confidence = 0.95) {
    try {
      const data = await riskApi.getCVaR(tickers.join(','), weights.join(','), confidence)
      cvarData.value = data
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'CVaR failed'
    }
  }

  async function fetchDrawdown(ticker: string) {
    try {
      drawdownData.value = await riskApi.getDrawdown(ticker)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Drawdown fetch failed'
    }
  }

  async function runStressTest(scenario: string, tickers: string[], weights?: number[]) {
    try {
      stressTestResult.value = await riskApi.runStressTest(scenario, tickers, weights)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Stress test failed'
    }
  }

  // P0-2: Update circuit breaker state from external data
  function updateCircuitBreakerState(data: {
    triggered: boolean
    dailyPnl: number
    dailyPnlPct: number
    drawdown: number
    cooldown?: number
  }) {
    circuitBreakerTriggered.value = data.triggered
    dailyPnl.value = data.dailyPnl
    dailyPnlPct.value = data.dailyPnlPct
    currentDrawdown.value = data.drawdown
    circuitBreakerCooldown.value = data.cooldown ?? 0
  }

  return {
    barraExposures, covarianceMatrix, varData, cvarData, drawdownData,
    stressTestResult, loading, error,
    circuitBreakerTriggered, dailyPnl, dailyPnlPct, currentDrawdown,
    circuitBreakerCooldown, riskLevel,
    fetchBarra, fetchVaR, fetchCVaR, fetchDrawdown, runStressTest,
    updateCircuitBreakerState,
  }
})
