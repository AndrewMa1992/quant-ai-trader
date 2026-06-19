<script setup lang="ts">
interface CBStatus {
  halted: boolean
  halt_reason: string
  consecutive_losses: number
  cooling_active: boolean
  cooling_remaining_minutes: number
  daily_loss_pct: number
}

defineProps<{ status: CBStatus }>()
</script>

<template>
  <div class="bg-bg-card rounded-lg p-4 border"
    :class="status.halted ? 'border-accent-red' : status.cooling_active ? 'border-accent-yellow' : 'border-accent-green'"
  >
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-semibold text-text-primary">Circuit Breaker</h3>
      <span class="w-3 h-3 rounded-full"
        :class="status.halted ? 'bg-accent-red' : status.cooling_active ? 'bg-accent-yellow' : 'bg-accent-green'" />
    </div>

    <div class="space-y-2 text-xs">
      <div class="flex justify-between">
        <span class="text-text-muted">Status</span>
        <span class="font-medium"
          :class="status.halted ? 'text-accent-red' : status.cooling_active ? 'text-accent-yellow' : 'text-accent-green'"
        >{{ status.halted ? 'HALTED' : status.cooling_active ? 'COOLING' : 'OK' }}</span>
      </div>

      <div v-if="status.halted" class="bg-accent-red/10 text-accent-red px-3 py-1.5 rounded text-xs">
        {{ status.halt_reason }}
      </div>

      <div v-if="status.cooling_active" class="bg-accent-yellow/10 text-accent-yellow px-3 py-1.5 rounded text-xs">
        Cooling: {{ status.cooling_remaining_minutes.toFixed(0) }} min remaining
      </div>

      <div class="flex justify-between">
        <span class="text-text-muted">Consec. Losses</span>
        <span :class="status.consecutive_losses >= 3 ? 'text-accent-red font-bold' : 'text-text-primary'">{{ status.consecutive_losses }}</span>
      </div>

      <div class="flex justify-between">
        <span class="text-text-muted">Daily P&L</span>
        <span :class="status.daily_loss_pct > 5 ? 'text-accent-red' : status.daily_loss_pct > 0 ? 'text-accent-green' : 'text-text-primary'">
          {{ status.daily_loss_pct > 0 ? '+' : '' }}{{ status.daily_loss_pct.toFixed(2) }}%
        </span>
      </div>
    </div>
  </div>
</template>
