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
      class="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium"
      :class="info.is_open ? 'bg-accent-green/20 text-accent-green' : 'bg-text-muted/20 text-text-muted'"
    >
      <span class="w-1.5 h-1.5 rounded-full"
        :class="info.is_open ? 'bg-accent-green' : 'bg-text-muted'" />
      <span>{{ market }}</span>
      <span>{{ info.is_open ? 'Open' : 'Closed' }}</span>
    </div>
  </div>
</template>
