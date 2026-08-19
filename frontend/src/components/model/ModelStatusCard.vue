<script setup lang="ts">
interface Version {
  version: number
  stage: string
  status: string
}

interface Model {
  name: string
  latest_versions: Version[]
  description: string
  loaded?: boolean
  metrics?: Record<string, number>
}

const props = defineProps<{ model: Model }>()

const latest = props.model.latest_versions?.[0]

function stageClass(s: string = '') {
  if (s === 'production') return 'bg-xm-profit-bg text-xm-profit'
  if (s === 'staging') return 'bg-yellow-50 text-yellow-700'
  return 'bg-xm-bg-surface text-xm-text-tertiary'
}

function formatName(name: string): string {
  return name.replace(/^quant-/, '').toUpperCase()
}
</script>

<template>
  <div class="bg-xm-bg-card rounded-lg p-4 shadow-xm border border-xm-border-light">
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-semibold text-xm-text-primary">{{ formatName(model.name) }}</h3>
      <span
        class="w-2.5 h-2.5 rounded-full"
        :class="model.loaded ? 'bg-risk-green animate-pulse' : 'bg-xm-text-tertiary'"
      />
    </div>

    <div v-if="latest" class="space-y-2 text-xs">
      <div class="flex justify-between">
        <span class="text-xm-text-tertiary">Version</span>
        <span class="text-xm-text-primary">v{{ latest.version }}</span>
      </div>
      <div class="flex justify-between items-center">
        <span class="text-xm-text-tertiary">Stage</span>
        <span class="px-2 py-0.5 rounded text-xxs font-semibold" :class="stageClass(latest.stage)">
          {{ latest.stage }}
        </span>
      </div>
      <div class="flex justify-between">
        <span class="text-xm-text-tertiary">Status</span>
        <span class="text-xm-text-primary">{{ latest.status }}</span>
      </div>
    </div>
    <p v-else class="text-xs text-xm-text-tertiary">No version registered</p>

    <p v-if="model.description" class="mt-3 text-xs text-xm-text-secondary line-clamp-2">
      {{ model.description }}
    </p>
  </div>
</template>
