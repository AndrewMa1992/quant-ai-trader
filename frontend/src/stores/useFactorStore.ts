/** stores/useFactorStore.ts – Factor data Pinia store */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { factorApi, type FactorDef, type ICAnalysis } from '../api/factorApi'

export const useFactorStore = defineStore('factor', () => {
  const factors = ref<FactorDef[]>([])
  const categories = ref<Record<string, number>>({})
  const loading = ref(false)
  const error = ref('')

  const icData = ref<ICAnalysis | null>(null)
  const correlationMatrix = ref<Record<string, Record<string, number>>>({})
  const redundantPairs = ref<{ factor_1: string; factor_2: string; correlation: number }[]>([])
  const decayData = ref<{ lag: number; ic: number; half_life?: number }[]>([])
  const icLoading = ref(false)

  async function fetchFactors(category?: string) {
    loading.value = true
    error.value = ''
    try {
      const data = await factorApi.listFactors(category)
      factors.value = data.factors ?? []
      categories.value = data.categories ?? {}
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch factors'
    } finally {
      loading.value = false
    }
  }

  async function fetchIC(factorName: string, window = 252) {
    icLoading.value = true
    try {
      const data = await factorApi.getICAnalysis(factorName, window)
      icData.value = data
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'IC analysis failed'
    } finally {
      icLoading.value = false
    }
  }

  async function fetchCorrelation(factorNames: string[]) {
    try {
      const names = factorNames.join(',')
      const data = await factorApi.getCorrelation(names)
      correlationMatrix.value = data.correlation_matrix ?? {}
      redundantPairs.value = data.redundant_pairs ?? []
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Correlation failed'
    }
  }

  async function fetchDecay(factorName: string, maxLags = 20) {
    try {
      const data = await factorApi.getDecay(factorName, maxLags)
      decayData.value = data.decay_curve ?? []
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Decay analysis failed'
    }
  }

  return {
    factors, categories, loading, error,
    icData, correlationMatrix, redundantPairs, decayData, icLoading,
    fetchFactors, fetchIC, fetchCorrelation, fetchDecay,
  }
})
