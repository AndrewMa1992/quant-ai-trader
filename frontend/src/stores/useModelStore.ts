/** stores/useModelStore.ts – Model data Pinia store v2.1 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { modelApi } from '../api/modelApi'

export interface ModelVersion {
  version: number
  stage: string
  status: string
}

export interface RegisteredModel {
  name: string
  latest_versions: ModelVersion[]
  description: string
}

export interface ModelStatus {
  loaded: boolean
  model_name: string
}

export interface SignalResult {
  ticker: string
  signal: number
  confidence: number
  direction: string
  components: Record<string, number>
}

export const useModelStore = defineStore('model', () => {
  const models = ref<RegisteredModel[]>([])
  const modelStatus = ref<Record<string, ModelStatus>>({})
  const trainingRuns = ref<Record<string, { status: string; metrics: Record<string, number> }>>({})
  const signals = ref<SignalResult[]>([])
  const loading = ref(false)
  const error = ref('')

  // Training progress state
  const trainingProgress = ref(0)
  const trainingEpoch = ref(0)
  const isTraining = ref(false)

  async function fetchModels() {
    loading.value = true
    error.value = ''
    try {
      const data = await modelApi.listModels()
      models.value = data.models ?? []
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch models'
    } finally {
      loading.value = false
    }
  }

  async function fetchModelStatus() {
    try {
      const data = await modelApi.getModelsStatus()
      modelStatus.value = data ?? {}
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Model status failed'
    }
  }

  async function startTraining(modelType: string, tickers: string[], hyperparams: Record<string, unknown> = {}) {
    try {
      const data = await modelApi.train(modelType, tickers, hyperparams)
      trainingRuns.value[data.run_id] = { status: 'queued', metrics: {} }
      isTraining.value = true
      trainingProgress.value = 0
      trainingEpoch.value = 0
      return data.run_id
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Training failed'
      return ''
    }
  }

  async function pollTrainingStatus(runId: string) {
    try {
      const data = await modelApi.getTrainingStatus(runId)
      trainingRuns.value[runId] = { status: data.status, metrics: data.metrics ?? {} }
      if (data.metrics?.progress !== undefined) {
        trainingProgress.value = data.metrics.progress
      }
      if (data.metrics?.epoch !== undefined) {
        trainingEpoch.value = data.metrics.epoch
      }
      if (data.status === 'completed' || data.status === 'failed') {
        isTraining.value = false
      }
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Status check failed'
    }
  }

  async function fetchAllSignals() {
    try {
      const data = await modelApi.getAllSignals()
      signals.value = data.signals ?? []
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Signal fetch failed'
    }
  }

  async function getSignal(ticker: string): Promise<SignalResult | null> {
    try {
      return await modelApi.getSignal(ticker)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Signal failed'
      return null
    }
  }

  return {
    models, modelStatus, trainingRuns, signals, loading, error,
    trainingProgress, trainingEpoch, isTraining,
    fetchModels, fetchModelStatus, startTraining, pollTrainingStatus,
    fetchAllSignals, getSignal,
  }
})
