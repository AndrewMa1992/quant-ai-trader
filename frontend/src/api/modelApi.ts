/** api/modelApi.ts – /api/v2/train/* + /api/v2/infer/* endpoints */
import apiClient from './index'

const TRAIN_BASE = '/v2/train'
const INFER_BASE = '/v2/infer'

export interface ModelInfo {
  name: string
  latest_versions: {
    version: number
    stage: string
    status: string
  }[]
}

export interface TrainingRun {
  run_id: string
  status: string
  model_type: string
  metrics: Record<string, number>
  error?: string
}

export interface SignalResult {
  ticker: string
  signal: number
  confidence: number
  direction: string
  components: Record<string, number>
}

export const modelApi = {
  // Training
  async listModels() {
    const { data } = await apiClient.get(`${TRAIN_BASE}/models`)
    return data.data
  },

  async train(modelType: string, tickers: string[], hyperparams: Record<string, unknown> = {}) {
    const { data } = await apiClient.post(`${TRAIN_BASE}/train/${modelType}`, {
      tickers,
      hyperparams,
    })
    return data.data
  },

  async getTrainingStatus(runId: string): Promise<TrainingRun> {
    const { data } = await apiClient.get(`${TRAIN_BASE}/training/${runId}`)
    return data.data
  },

  async hyperopt(modelType: string, tickers: string[], nTrials = 100) {
    const { data } = await apiClient.post(`${TRAIN_BASE}/hyperopt`, {
      model_type: modelType,
      tickers,
      n_trials: nTrials,
    })
    return data.data
  },

  // Inference
  async predict(ticker: string, features?: Record<string, number>) {
    const { data } = await apiClient.post(`${INFER_BASE}/predict`, { ticker, features })
    return data.data
  },

  async predictBatch(tickers: string[]) {
    const { data } = await apiClient.post(`${INFER_BASE}/predict/batch`, { tickers })
    return data.data
  },

  async getSignal(ticker: string): Promise<SignalResult> {
    const { data } = await apiClient.post(`${INFER_BASE}/signal`, { ticker })
    return data.data
  },

  async getAllSignals() {
    const { data } = await apiClient.post(`${INFER_BASE}/signal/all`)
    return data.data
  },

  async getModelsStatus() {
    const { data } = await apiClient.get(`${INFER_BASE}/models/status`)
    return data.data
  },
}
