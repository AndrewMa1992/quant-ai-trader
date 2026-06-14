<script setup lang="ts">
import { computed } from 'vue'
import XmCard from '@/components/ui/XmCard.vue'
import XmStatusDot from '@/components/ui/XmStatusDot.vue'
import XmBadge from '@/components/ui/XmBadge.vue'

interface Props {
  triggered: boolean
  dailyPnlPct: number
  dailyLossLimit: number
  drawdown: number
  maxDrawdown: number
  cooldownRemaining: number
}

const props = defineProps<Props>()

const status = computed(() => {
  if (props.triggered) return 'triggered'
  if (props.dailyPnlPct <= -props.dailyLossLimit * 0.7 || props.drawdown >= props.maxDrawdown * 0.7) return 'warning'
  return 'normal'
})

const statusConfig = computed(() => {
  switch (status.value) {
    case 'triggered':
      return { color: 'red', label: 'TRIGGERED', variant: 'danger' as const }
    case 'warning':
      return { color: 'yellow', label: 'WARNING', variant: 'warning' as const }
    default:
      return { color: 'green', label: 'NORMAL', variant: 'success' as const }
  }
})
</script>

<template>
  <XmCard title="Circuit Breaker" class="!p-5">
    <!-- Status indicator -->
    <div class="flex items-center gap-3 mb-4">
      <XmStatusDot
        :status="statusConfig.color as 'green' | 'yellow' | 'red'"
        :pulsing="status === 'triggered'"
      />
      <span class="text-sm font-semibold">{{ statusConfig.label }}</span>
      <XmBadge :variant="statusConfig.variant">{{ statusConfig.label }}</XmBadge>
    </div>

    <!-- Metrics -->
    <div class="space-y-3">
      <div class="flex justify-between items-center">
        <span class="text-xs text-xm-text-secondary">Daily P&L</span>
        <span
          class="text-sm font-mono font-semibold"
          :class="dailyPnlPct >= 0 ? 'xm-pnl-positive' : 'xm-pnl-negative'"
        >
          {{ (dailyPnlPct * 100).toFixed(2) }}%
        </span>
      </div>
      <!-- Daily loss progress bar -->
      <div class="w-full h-2 bg-xm-bg-surface rounded-full overflow-hidden">
        <div
          class="h-full rounded-full transition-all duration-500"
          :class="dailyPnlPct <= -dailyLossLimit * 0.7 ? 'bg-risk-yellow' : 'bg-risk-green'"
          :style="{ width: Math.min(Math.abs(dailyPnlPct) / dailyLossLimit * 100, 100) + '%' }"
        />
      </div>
      <div class="flex justify-between text-xxs text-xm-text-tertiary">
        <span>Loss Limit: {{ (dailyLossLimit * 100).toFixed(1) }}%</span>
        <span>{{ (Math.abs(dailyPnlPct) * 100).toFixed(1) }}% used</span>
      </div>

      <div class="flex justify-between items-center pt-1">
        <span class="text-xs text-xm-text-secondary">Drawdown</span>
        <span class="text-sm font-mono font-semibold text-risk-yellow">
          {{ (drawdown * 100).toFixed(2) }}%
        </span>
      </div>
      <div class="w-full h-2 bg-xm-bg-surface rounded-full overflow-hidden">
        <div
          class="h-full rounded-full transition-all duration-500"
          :class="drawdown >= maxDrawdown * 0.7 ? 'bg-risk-red' : 'bg-risk-yellow'"
          :style="{ width: Math.min(drawdown / maxDrawdown * 100, 100) + '%' }"
        />
      </div>
      <div class="flex justify-between text-xxs text-xm-text-tertiary">
        <span>Max DD: {{ (maxDrawdown * 100).toFixed(0) }}%</span>
        <span>{{ (drawdown * 100).toFixed(1) }}%</span>
      </div>

      <!-- Cooldown -->
      <div v-if="triggered && cooldownRemaining > 0" class="pt-2 border-t border-xm-border-light">
        <div class="flex justify-between items-center">
          <span class="text-xs text-xm-text-secondary">Cooldown</span>
          <span class="text-sm font-mono text-risk-red font-semibold">
            {{ Math.ceil(cooldownRemaining / 60) }}m {{ cooldownRemaining % 60 }}s
          </span>
        </div>
      </div>
    </div>
  </XmCard>
</template>
