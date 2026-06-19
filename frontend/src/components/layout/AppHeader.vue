<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useExecutionStore } from '@/stores/useExecutionStore'

const route = useRoute()
const execStore = useExecutionStore()

const currentTime = ref<string>('')

let timer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  currentTime.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  timer = setInterval(() => {
    currentTime.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  }, 1000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

const pageTitle = computed(() => {
  const map: Record<string, string> = {
    Dashboard: 'Dashboard',
    FactorResearch: 'Factor Research',
    ModelCenter: 'Model Center',
    RiskDashboard: 'Risk Dashboard',
    PortfolioOptimizer: 'Portfolio Optimizer',
    BacktestAnalysis: 'Backtest Analysis',
    ExecutionMonitor: 'Execution Monitor',
  }
  return map[String(route.name)] ?? 'Quant AI Trader'
})

const alertCount = computed(() => execStore.alerts.length)
const criticalCount = computed(() =>
  execStore.alerts.filter((a) => a.severity === 'CRITICAL').length,
)
</script>

<template>
  <header class="flex items-center justify-between h-14 px-6 bg-white border-b border-xm-border-light shrink-0">
    <!-- Left: Page title -->
    <div class="flex items-center gap-3">
      <span class="text-sm font-semibold text-xm-text-primary">{{ pageTitle }}</span>
    </div>

    <!-- Right: Status + time -->
    <div class="flex items-center gap-4">
      <!-- Alerts -->
      <div v-if="alertCount > 0" class="relative cursor-pointer" title="Alerts">
        <span class="text-xm-text-secondary text-sm">🔔</span>
        <span
          v-if="criticalCount > 0"
          class="absolute -top-1 -right-2 w-4 h-4 bg-risk-red text-white text-xxs rounded-full flex items-center justify-center font-bold"
        >{{ criticalCount }}</span>
      </div>

      <!-- System status -->
      <div class="flex items-center gap-2">
        <span class="w-2 h-2 rounded-full bg-risk-green animate-pulse" />
        <span class="text-xs text-xm-text-secondary font-medium">Live</span>
      </div>

      <!-- Clock -->
      <span class="text-xs text-xm-text-tertiary font-mono tabular-nums min-w-[70px]">
        {{ currentTime }}
      </span>
    </div>
  </header>
</template>
