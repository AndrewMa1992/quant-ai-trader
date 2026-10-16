/** stores/useFactorStore.ts – Factor data Pinia store */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { factorApi, type FactorDef, type ICAnalysis } from '../api/factorApi'

export const useFactorStore = defineStore('factor', () => {
  const factors = ref<FactorDef[]>([])
  const categories = ref<Record<string, number>>({})
  const loading = ref(false)
  const error = ref('')

  const icById = ref<Record<string, { ic_mean: number; ic_std: number; ir: number }>>({})
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

  async function fetchICSummary() {
    try {
      const data = await factorApi.getICSummary()
      const rows = (data?.factors ?? []) as Array<Record<string, unknown>>
      const next: Record<string, { ic_mean: number; ic_std: number; ir: number }> = {}
      for (const row of rows) {
        const id = String(row.id ?? '')
        if (!id) continue
        next[id] = {
          ic_mean: Number(row.ic_mean ?? 0),
          ic_std: Number(row.ic_std ?? 0),
          ir: Number(row.ir ?? 0),
        }
        const match = factors.value.find((f) => f.id === id)
        if (match) {
          match.ic_mean = next[id].ic_mean
          match.ic_std = next[id].ic_std
          match.ir = next[id].ir
        }
      }
      icById.value = next
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'IC summary failed'
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
    factors, categories, loading, error, icById,
    icData, correlationMatrix, redundantPairs, decayData, icLoading,
    fetchFactors, fetchICSummary, fetchIC, fetchCorrelation, fetchDecay,
  }
})
