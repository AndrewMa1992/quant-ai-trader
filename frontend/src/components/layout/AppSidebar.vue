<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

interface NavItem {
  path: string
  name: string
  label: string
  icon: string
}

const navItems: NavItem[] = [
  { path: '/', name: 'Dashboard', label: 'Dashboard', icon: 'Dash' },
  { path: '/factors', name: 'FactorResearch', label: 'Factors', icon: 'Fac' },
  { path: '/models', name: 'ModelCenter', label: 'Models', icon: 'ML' },
  { path: '/risk', name: 'RiskDashboard', label: 'Risk', icon: 'Risk' },
  { path: '/portfolio', name: 'PortfolioOptimizer', label: 'Portfolio', icon: 'Port' },
  { path: '/backtest', name: 'BacktestAnalysis', label: 'Backtest', icon: 'BT' },
  { path: '/execution', name: 'ExecutionMonitor', label: 'Execution', icon: 'Exec' },
  { path: '/orders', name: 'OrderHistory', label: 'Orders', icon: 'Ord' },
  { path: '/data', name: 'DataExplorer', label: 'Data', icon: 'Data' },
  { path: '/sync', name: 'DataSyncDashboard', label: 'Sync', icon: 'Sync' },
]

const activeIndex = computed(() => navItems.findIndex((item) => item.name === route.name))

function navigate(path: string) {
  router.push(path)
}
</script>

<template>
  <aside class="w-[240px] bg-xm-bg-sidebar border-r border-xm-border-light flex flex-col shrink-0">
    <!-- Logo -->
    <div class="px-5 py-4 border-b border-xm-border-light">
      <div class="flex items-center gap-3">
        <div class="w-8 h-8 rounded-lg bg-xm-primary flex items-center justify-center">
          <span class="text-white text-sm font-bold">Q</span>
        </div>
        <div>
          <h1 class="text-sm font-semibold text-xm-text-primary leading-none">Quant AI Trader</h1>
          <p class="text-xxs text-xm-text-tertiary mt-0.5">v2.1</p>
        </div>
      </div>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
      <button
        v-for="(item, idx) in navItems"
        :key="item.name"
        class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-xm ease-xm text-left"
        :class="idx === activeIndex
          ? 'bg-xm-primary-light text-xm-primary'
          : 'text-xm-text-secondary hover:text-xm-text-primary hover:bg-xm-bg-surface'"
        @click="navigate(item.path)"
      >
        <span
          class="flex-shrink-0 w-8 text-center text-xxs font-mono font-semibold tracking-wide uppercase opacity-70"
        >{{ item.icon }}</span>
        <span>{{ item.label }}</span>
        <div
          v-if="idx === activeIndex"
          class="ml-auto w-1 h-4 rounded-full bg-xm-primary"
        />
      </button>
    </nav>

    <!-- Footer status -->
    <div class="p-4 border-t border-xm-border-light">
      <div class="flex items-center gap-2 text-xs text-xm-text-tertiary">
        <span class="w-2 h-2 rounded-full bg-risk-green" />
        <span>System Active</span>
      </div>
    </div>
  </aside>
</template>
