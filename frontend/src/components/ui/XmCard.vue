<script setup lang="ts">
interface Props {
  title?: string
  subtitle?: string
  hoverable?: boolean
  padding?: string
}

withDefaults(defineProps<Props>(), {
  hoverable: false,
  padding: 'p-5',
})
</script>

<template>
  <div class="xm-card" :class="[{ 'cursor-pointer': hoverable }, padding]">
    <div v-if="title || $slots.header" class="flex items-center justify-between mb-4">
      <div>
        <h3 v-if="title" class="text-sm font-semibold text-xm-text-primary">{{ title }}</h3>
        <p v-if="subtitle" class="text-xs text-xm-text-tertiary mt-0.5">{{ subtitle }}</p>
      </div>
      <slot v-if="$slots.header" name="header" />
    </div>
    <slot />
  </div>
</template>
