<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import XmCard from '@/components/ui/XmCard.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import XmStatusDot from '@/components/ui/XmStatusDot.vue'
import ModelStatusCard from '@/components/model/ModelStatusCard.vue'
import { useModelStore } from '@/stores/useModelStore'
import type { RegisteredModel, ModelStatus } from '@/stores/useModelStore'

const modelStore = useModelStore()

const DEFAULT_TICKERS = ['AAPL', 'MSFT', 'GOOGL', 'SPY']

const modelType = ref('transformer')
const tickersInput = ref(DEFAULT_TICKERS.join(','))
const currentRunId = ref('')
const trainError = ref('')
const loading = ref(false)

let pollTimer: ReturnType<typeof setInterval> | undefined

function inferType(name: string): string {
  const lower = name.toLowerCase()
  if (lower.includes('transformer') || lower.includes('patchtst')) return 'Transformer'
  if (lower.includes('rl') || lower.includes('ppo') || lower.includes('agent')) return 'RL'
  if (lower.includes('bert') || lower.includes('sentiment') || lower.includes('nlp')) return 'NLP'
  if (lower.includes('xgboost') || lower.includes('gbdt') || lower.includes('ensemble')) return 'GBDT'
  if (lower.includes('lstm') || lower.includes('gru')) return 'RNN'
  return 'Model'
}

function statusDotColor(status: string): 'green' | 'yellow' | 'red' {
  const s = status.toLowerCase()
  if (s === 'ready' || s === 'active' || s === 'loaded' || s === 'completed') return 'green'
  if (s === 'staging' || s === 'archived' || s === 'pending' || s === 'queued' || s === 'running') return 'yellow'
  return 'red'
}

function resolveStatus(model: RegisteredModel, statusMap: Record<string, ModelStatus>): string {
  const explicit = statusMap[model.name]
  if (explicit?.loaded) return 'ready'
  const latest = model.latest_versions?.[0]
  if (latest?.status) return latest.status
  return 'unknown'
}

const models = computed(() => {
  const statusMap = modelStore.modelStatus ?? {}
  return modelStore.models.map((m) => {
    const status = resolveStatus(m, statusMap)
    const loaded = statusMap[m.name]?.loaded ?? false
    return {
      name: m.name,
      type: inferType(m.name),
      status,
      statusDot: statusDotColor(status),
      description: m.description || '',
      latest_versions: m.latest_versions ?? [],
      loaded,
      metrics: modelStore.trainingRuns[m.name]?.metrics,
    }
  })
})

const statusCards = computed(() => {
  const statusMap = modelStore.modelStatus ?? {}
  const names = Object.keys(statusMap)
  if (names.length === 0) {
    return models.value.map((m) => ({
      name: m.name,
      latest_versions: m.latest_versions,
      description: m.description,
      loaded: m.loaded,
      metrics: m.metrics,
    }))
  }
  return names.map((name) => {
    const registered = modelStore.models.find((m) => m.name === name)
    return {
      name,
      latest_versions: registered?.latest_versions ?? [],
      description: registered?.description ?? '',
      loaded: statusMap[name]?.loaded ?? false,
      metrics: modelStore.trainingRuns[name]?.metrics,
    }
  })
})

const noModels = computed(() => !loading.value && models.value.length === 0 && statusCards.value.length === 0)
const training = computed(() => modelStore.isTraining)
const trainingProgress = computed(() => modelStore.trainingProgress)
const trainingEpoch = computed(() => modelStore.trainingEpoch)
const runStatus = computed(() => {
  if (!currentRunId.value) return ''
  return modelStore.trainingRuns[currentRunId.value]?.status ?? ''
})

function clearPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = undefined
  }
}

async function refreshModels() {
  loading.value = true
  try {
    await Promise.allSettled([
      modelStore.fetchModels(),
      modelStore.fetchModelStatus(),
    ])
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  refreshModels()
})

onUnmounted(() => {
  clearPoll()
})

async function startTraining() {
  trainError.value = ''
  const tickers = tickersInput.value
    .split(',')
    .map((t) => t.trim().toUpperCase())
    .filter(Boolean)
  if (tickers.length === 0) {
    trainError.value = 'Enter at least one ticker'
    return
  }

  clearPoll()
  const runId = await modelStore.startTraining(modelType.value, tickers)
  if (!runId) {
    trainError.value = modelStore.error || 'Failed to start training'
    return
  }

  currentRunId.value = runId
  pollTimer = setInterval(async () => {
    await modelStore.pollTrainingStatus(runId)
    const status = modelStore.trainingRuns[runId]?.status
    if (status === 'completed' || status === 'failed') {
      clearPoll()
      await refreshModels()
    }
  }, 2000)
}
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <XmCard title="Model Training" class="!p-5">
      <template #header>
        <XmBadge :variant="training ? 'warning' : 'success'">
          {{ training ? 'Training...' : 'Ready' }}
        </XmBadge>
      </template>

      <div class="space-y-4">
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <label class="block text-xxs text-xm-text-tertiary mb-1">Model Type</label>
            <select v-model="modelType" class="xm-input w-full" :disabled="training">
              <option value="transformer">Transformer (PatchTST)</option>
              <option value="gbdt">GBDT (LightGBM)</option>
              <option value="tcn">TCN</option>
              <option value="tft">TFT</option>
              <option value="rl">RL (PPO)</option>
            </select>
          </div>
          <div class="sm:col-span-2">
            <label class="block text-xxs text-xm-text-tertiary mb-1">Tickers</label>
            <input
              v-model="tickersInput"
              class="xm-input w-full"
              placeholder="AAPL,MSFT,GOOGL,SPY"
              :disabled="training"
            />
          </div>
        </div>

        <div class="flex items-center gap-4 flex-wrap">
          <button
            class="px-5 py-2.5 rounded-lg text-sm font-semibold text-white transition-all duration-xm ease-xm disabled:opacity-50"
            :class="training ? 'bg-xm-bg-surface text-xm-text-tertiary cursor-not-allowed' : 'bg-xm-primary hover:bg-xm-primary-hover'"
            :disabled="training"
            @click="startTraining"
          >
            {{ training ? 'Training in Progress...' : 'Start Training' }}
          </button>
          <span v-if="currentRunId" class="text-xs text-xm-text-tertiary font-mono">
            Run: {{ currentRunId }}
            <template v-if="runStatus"> · {{ runStatus }}</template>
          </span>
          <span v-if="training" class="text-sm text-xm-text-secondary">
            Epoch {{ trainingEpoch }}
          </span>
        </div>

        <div v-if="trainError" class="text-sm text-loss">{{ trainError }}</div>
        <div v-if="modelStore.error && !trainError" class="text-sm text-loss">{{ modelStore.error }}</div>

        <div v-if="training || trainingProgress > 0" class="space-y-1">
          <div class="w-full h-2.5 bg-xm-bg-surface rounded-full overflow-hidden">
            <div
              class="h-full rounded-full transition-all duration-300"
              style="background: linear-gradient(90deg, #FF6700, #E55A00)"
              :style="{ width: Math.min(100, Math.max(0, trainingProgress)) + '%' }"
            />
          </div>
          <div class="text-right text-xxs text-xm-text-tertiary">
            {{ Math.min(100, Math.max(0, trainingProgress)).toFixed(0) }}%
          </div>
        </div>
      </div>
    </XmCard>

    <XmCard title="Model Status" subtitle="Live status from inference service">
      <div v-if="loading" class="text-center py-8 text-xm-text-tertiary text-sm">
        Loading models...
      </div>
      <div v-else-if="noModels" class="text-center py-8 text-xm-text-tertiary text-sm">
        No models registered. Start a training run to populate status.
      </div>
      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <ModelStatusCard
          v-for="card in statusCards"
          :key="card.name"
          :model="card"
        />
      </div>
    </XmCard>

    <div v-if="models.length > 0" class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <XmCard v-for="model in models" :key="model.name" class="!p-5">
        <div class="flex items-start justify-between mb-3">
          <div>
            <h4 class="text-sm font-semibold">{{ model.name }}</h4>
            <span class="text-xs text-xm-text-tertiary">{{ model.type }}</span>
          </div>
          <div class="flex items-center gap-2">
            <XmStatusDot :status="model.statusDot" />
            <span class="text-xs text-xm-text-secondary capitalize">{{ model.status }}</span>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <div class="xm-metric-label">Loaded</div>
            <div class="text-sm font-mono font-semibold mt-0.5">
              {{ model.loaded ? 'Yes' : 'No' }}
            </div>
          </div>
          <div>
            <div class="xm-metric-label">Version</div>
            <div class="text-sm font-mono mt-0.5 text-xm-text-secondary">
              {{ model.latest_versions?.[0] ? `v${model.latest_versions[0].version}` : '—' }}
            </div>
          </div>
        </div>
      </XmCard>
    </div>
  </div>
</template>
