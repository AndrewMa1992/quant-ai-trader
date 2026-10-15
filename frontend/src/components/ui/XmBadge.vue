<script setup lang="ts">
import type { BadgeVariant } from '@/types/ui'

withDefaults(defineProps<{
  variant?: BadgeVariant
}>(), {
  variant: 'info',
})
</script>

<template>
  <span class="xm-badge" :class="`xm-badge-${variant}`">
    <slot />
  </span>
</template>
