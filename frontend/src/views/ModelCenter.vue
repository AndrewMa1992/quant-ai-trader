<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import XmCard from '@/components/ui/XmCard.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import XmStatusDot from '@/components/ui/XmStatusDot.vue'
import { useModelStore } from '@/stores/useModelStore'
import type { RegisteredModel, ModelStatus } from '@/stores/useModelStore'

use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const modelStore = useModelStore()

const training = ref(false)
const trainingProgress = ref(0)
const trainingEpoch = ref(0)
const totalEpochs = 30

interface ModelEntry {
  name: string
  type: string
  status: string
  statusDot: 'green' | 'yellow' | 'red'
  sharpe: number | null
  pnl: number | null
  winRate: number | null
  lastTrained: string
}

/** Derive a display-friendly type label from the model name. */
function inferType(name: string): string {
  const lower = name.toLowerCase()
  if (lower.includes('transformer') || lower.includes('patchtst')) return 'Transformer'
  if (lower.includes('rl') || lower.includes('ppo') || lower.includes('agent')) return 'RL'
  if (lower.includes('bert') || lower.includes('sentiment') || lower.includes('nlp')) return 'NLP'
  if (lower.includes('xgboost') || lower.includes('gbdt') || lower.includes('ensemble')) return 'GBDT'
  if (lower.includes('lstm') || lower.includes('gru')) return 'RNN'
  return 'Model'
}

/** Derive a dot colour from status string. */
function statusDotColor(status: string): 'green' | 'yellow' | 'red' {
  const s = status.toLowerCase()
  if (s === 'ready' || s === 'active' || s === 'loaded') return 'green'
  if (s === 'staging' || s === 'archived' || s === 'pending') return 'yellow'
  return 'red'
}

/** Resolve model status from combined store data. */
function resolveStatus(model: RegisteredModel, statusMap: Record<string, ModelStatus>): string {
  const explicit = statusMap[model.name]
  if (explicit?.loaded) return 'ready'
  const latest = model.latest_versions?.[0]
  if (latest?.status) return latest.status
  return 'unknown'
}

/** Build display entries from store data. */
const models = computed<ModelEntry[]>(() => {
  const statusMap = modelStore.modelStatus ?? {}
  return modelStore.models.map((m) => {
    const status = resolveStatus(m, statusMap)
    return {
      name: m.name,
      type: inferType(m.name),
      status,
      statusDot: statusDotColor(status),
      sharpe: null,
      pnl: null,
      winRate: null,
      lastTrained: m.latest_versions?.[0] ? `v${m.latest_versions[0].version}` : '—',
    }
  })
})

const loading = ref(false)
const noModels = computed(() => !loading.value && modelStore.models.length === 0)

let progressTimer: ReturnType<typeof setInterval> | undefined

onMounted(async () => {
  loading.value = true
  try {
    await modelStore.fetchModels()
    await modelStore.fetchModelStatus()
  } catch {
    // Silent degrade
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  if (progressTimer) clearInterval(progressTimer)
})

function startTraining() {
  training.value = true
  trainingProgress.value = 0
  trainingEpoch.value = 0
  progressTimer = setInterval(() => {
    if (trainingProgress.value >= 100) {
      training.value = false
      if (progressTimer) clearInterval(progressTimer)
      return
    }
    trainingProgress.value += Math.random() * 8
    if (trainingProgress.value > 100) trainingProgress.value = 100
    trainingEpoch.value = Math.floor((trainingProgress.value / 100) * totalEpochs)
  }, 400)
}

const pnlChartOption = computed(() => ({
  grid: { top: 8, right: 16, bottom: 4, left: 100 },
  tooltip: {
    trigger: 'axis' as const,
    backgroundColor: '#fff',
    borderColor: '#EEEEEE',
    textStyle: { color: '#1A1A1A', fontSize: 12 },
    axisPointer: { type: 'shadow' as const },
  },
  xAxis: {
    type: 'value' as const,
    splitLine: { lineStyle: { color: '#F5F5F5' } },
    axisLabel: { fontSize: 10, color: '#999999', formatter: (v: number) => `$${(v / 1000).toFixed(0)}K` },
  },
  yAxis: {
    type: 'category' as const,
    data: models.value.map((m) => m.name),
    axisLabel: { fontSize: 10, color: '#666666' },
    inverse: true,
  },
  series: [
    {
      type: 'bar',
      data: models.value.map((m) => ({
        value: m.pnl ?? 0,
        itemStyle: {
          color: (m.pnl ?? 0) >= 0 ? '#16A34A' : '#DC2626',
          borderRadius: [0, 4, 4, 0],
        },
      })),
      barWidth: 16,
    },
  ],
}))
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <!-- Training Panel -->
    <XmCard title="Model Training" class="!p-5">
      <template #header>
        <XmBadge :variant="training ? 'warning' : 'success'">
          {{ training ? 'Training...' : 'Ready' }}
        </XmBadge>
      </template>
      <div class="space-y-4">
        <div class="flex items-center gap-4">
          <button
            class="px-5 py-2.5 rounded-lg text-sm font-semibold text-white transition-all duration-xm ease-xm disabled:opacity-50"
            :class="training ? 'bg-xm-bg-surface text-xm-text-tertiary cursor-not-allowed' : 'bg-xm-primary hover:bg-xm-primary-hover'"
            :disabled="training"
            @click="startTraining"
          >
            {{ training ? 'Training in Progress...' : 'Start Full Training' }}
          </button>
          <span v-if="training" class="text-sm text-xm-text-secondary">
            Epoch {{ trainingEpoch }}/{{ totalEpochs }}
          </span>
        </div>
        <!-- Progress bar -->
        <div v-if="training" class="space-y-1">
          <div class="w-full h-2.5 bg-xm-bg-surface rounded-full overflow-hidden">
            <div
              class="h-full rounded-full transition-all duration-300"
              style="background: linear-gradient(90deg, #FF6700, #E55A00)"
              :style="{ width: trainingProgress + '%' }"
            />
          </div>
          <div class="text-right text-xxs text-xm-text-tertiary">
            {{ trainingProgress.toFixed(0) }}%
          </div>
        </div>
      </div>
    </XmCard>

    <!-- PnL Attribution -->
    <XmCard title="Model PnL Attribution">
      <div v-if="noModels" class="flex items-center justify-center h-[280px] text-xm-text-tertiary text-sm">
        No model data
      </div>
      <VChart v-else :option="pnlChartOption" style="height: 280px" autoresize />
    </XmCard>

    <!-- Model Status Cards -->
    <div v-if="loading" class="text-center py-8 text-xm-text-tertiary text-sm">
      Loading models...
    </div>
    <div v-else-if="noModels" class="text-center py-8 text-xm-text-tertiary text-sm">
      暂无训练模型
    </div>
    <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-4">
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
            <div class="xm-metric-label">Sharpe</div>
            <div class="text-sm font-mono font-semibold mt-0.5" :class="(model.sharpe ?? 0) >= 1 ? 'text-profit' : 'text-xm-text-secondary'">
              {{ model.sharpe !== null ? model.sharpe.toFixed(2) : '—' }}
            </div>
          </div>
          <div>
            <div class="xm-metric-label">PnL</div>
            <div class="text-sm font-mono font-semibold mt-0.5" :class="(model.pnl ?? 0) >= 0 ? 'xm-pnl-positive' : 'xm-pnl-negative'">
              {{ model.pnl !== null ? '$' + model.pnl.toLocaleString() : '—' }}
            </div>
          </div>
          <div>
            <div class="xm-metric-label">Win Rate</div>
            <div class="text-sm font-mono font-semibold mt-0.5">
              {{ model.winRate !== null ? (model.winRate * 100).toFixed(1) + '%' : '—' }}
            </div>
          </div>
          <div>
            <div class="xm-metric-label">Version</div>
            <div class="text-sm font-mono mt-0.5 text-xm-text-secondary">{{ model.lastTrained }}</div>
          </div>
        </div>
      </XmCard>
    </div>
  </div>
</template>
