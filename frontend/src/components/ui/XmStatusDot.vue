<script setup lang="ts">
interface Props {
  status?: 'green' | 'yellow' | 'red'
  pulsing?: boolean
}

withDefaults(defineProps<Props>(), {
  status: 'green',
  pulsing: false,
})
</script>

<template>
  <span
    class="xm-status-dot inline-block"
    :class="[`xm-status-dot--${status}`, { 'animate-pulse': pulsing }]"
  />
</template>
