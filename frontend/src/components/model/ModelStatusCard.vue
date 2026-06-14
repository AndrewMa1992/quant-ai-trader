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
const stageColor = (s: string = '') =>
  s === 'production' ? 'text-accent-green bg-accent-green/10' :
  s === 'staging' ? 'text-accent-yellow bg-accent-yellow/10' :
  'text-text-muted bg-text-muted/10'

function formatName(name: string): string {
  return name.replace(/^quant-/, '').toUpperCase()
}
</script>

<template>
  <div class="bg-bg-card rounded-lg p-4 shadow border border-border">
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-semibold text-text-primary">{{ formatName(model.name) }}</h3>
      <span class="w-2.5 h-2.5 rounded-full"
        :class="model.loaded ? 'bg-accent-green animate-pulse' : 'bg-text-muted'" />
    </div>

    <div v-if="latest" class="space-y-2 text-xs">
      <div class="flex justify-between">
        <span class="text-text-muted">Version</span>
        <span class="text-text-primary">v{{ latest.version }}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-text-muted">Stage</span>
        <span class="px-1.5 py-0.5 rounded text-xs font-medium" :class="stageColor(latest.stage)">
          {{ latest.stage ?? 'unknown' }}
        </span>
      </div>
    </div>

    <div v-if="model.metrics" class="mt-3 pt-3 border-t border-border space-y-1 text-xs">
      <div v-for="(val, key) in model.metrics" :key="key" class="flex justify-between">
        <span class="text-text-muted">{{ key }}</span>
        <span class="text-text-primary font-mono">{{ typeof val === 'number' ? val.toFixed(4) : val }}</span>
      </div>
    </div>

    <p v-if="model.description" class="text-xs text-text-muted mt-2 truncate">{{ model.description }}</p>
  </div>
</template>
