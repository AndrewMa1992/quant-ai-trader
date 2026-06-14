<script setup lang="ts">
interface Props {
  variant?: 'success' | 'warning' | 'danger' | 'info'
}

withDefaults(defineProps<Props>(), {
  variant: 'info',
})
</script>

<template>
  <span class="xm-badge" :class="`xm-badge-${variant}`">
    <slot />
  </span>
</template>
