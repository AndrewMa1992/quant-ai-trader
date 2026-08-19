<script setup lang="ts">
defineProps<{
  markets: Record<string, { is_open: boolean }>
}>()
</script>

<template>
  <div class="flex gap-3 flex-wrap">
    <div
      v-for="(info, market) in markets"
      :key="market"
      class="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium border"
      :class="info.is_open
        ? 'bg-xm-profit-bg text-xm-profit border-transparent'
        : 'bg-xm-bg-surface text-xm-text-tertiary border-xm-border-light'"
    >
      <span
        class="w-1.5 h-1.5 rounded-full"
        :class="info.is_open ? 'bg-risk-green' : 'bg-xm-text-tertiary'"
      />
      <span class="font-semibold">{{ market }}</span>
      <span>{{ info.is_open ? 'Open' : 'Closed' }}</span>
    </div>
  </div>
</template>
