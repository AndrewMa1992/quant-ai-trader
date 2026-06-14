<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import XmCard from '@/components/ui/XmCard.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import XmStatusDot from '@/components/ui/XmStatusDot.vue'
import { useExecutionStore } from '@/stores/useExecutionStore'

const execStore = useExecutionStore()

interface TradeLog {
  id: string
  ticker: string
  side: string
  quantity: number
  price: number
  value: number
  status: string
  timestamp: string
  algo: string
}

const tradeLogs = ref<TradeLog[]>([
  { id: 'T-001', ticker: 'AAPL', side: 'buy', quantity: 50, price: 195.20, value: 9760, status: 'filled', timestamp: '2025-06-08 10:32:15', algo: 'TWAP' },
  { id: 'T-002', ticker: 'MSFT', side: 'sell', quantity: 20, price: 420.45, value: 8409, status: 'filled', timestamp: '2025-06-08 10:35:42', algo: 'VWAP' },
  { id: 'T-003', ticker: 'NVDA', side: 'buy', quantity: 10, price: 875.30, value: 8753, status: 'partial', timestamp: '2025-06-08 10:38:01', algo: 'TWAP' },
  { id: 'T-004', ticker: '0700.HK', side: 'buy', quantity: 200, price: 38.50, value: 7700, status: 'filled', timestamp: '2025-06-08 10:41:20', algo: 'Iceberg' },
  { id: 'T-005', ticker: 'TSLA', side: 'sell', quantity: 30, price: 245.10, value: 7353, status: 'filled', timestamp: '2025-06-08 10:44:55', algo: 'TWAP' },
  { id: 'T-006', ticker: 'GOOGL', side: 'buy', quantity: 25, price: 175.80, value: 4395, status: 'filled', timestamp: '2025-06-08 10:48:12', algo: 'VWAP' },
  { id: 'T-007', ticker: 'META', side: 'buy', quantity: 15, price: 510.30, value: 7654, status: 'rejected', timestamp: '2025-06-08 10:51:30', algo: 'TWAP' },
  { id: 'T-008', ticker: 'AMZN', side: 'sell', quantity: 40, price: 187.20, value: 7488, status: 'filled', timestamp: '2025-06-08 10:55:00', algo: 'Iceberg' },
])

const todayStats = computed(() => {
  const filled = tradeLogs.value.filter(t => t.status === 'filled')
  const buys = filled.filter(t => t.side === 'buy')
  const sells = filled.filter(t => t.side === 'sell')
  const totalValue = filled.reduce((s, t) => s + t.value, 0)
  return {
    totalTrades: filled.length,
    buyCount: buys.length,
    sellCount: sells.length,
    totalValue,
    rejectedCount: tradeLogs.value.filter(t => t.status === 'rejected').length,
  }
})

onMounted(() => {
  execStore.fetchAlerts()
})

function statusBadge(status: string) {
  switch (status) {
    case 'filled': return 'success'
    case 'partial': return 'warning'
    case 'rejected': return 'danger'
    default: return 'info'
  }
}
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <!-- Stats Row -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <XmCard class="!p-4">
        <div class="xm-metric-label">Today's Trades</div>
        <div class="xm-metric-value text-lg">{{ todayStats.totalTrades }}</div>
      </XmCard>
      <XmCard class="!p-4">
        <div class="xm-metric-label">Buy Orders</div>
        <div class="xm-metric-value text-lg text-profit">{{ todayStats.buyCount }}</div>
      </XmCard>
      <XmCard class="!p-4">
        <div class="xm-metric-label">Sell Orders</div>
        <div class="xm-metric-value text-lg text-loss">{{ todayStats.sellCount }}</div>
      </XmCard>
      <XmCard class="!p-4">
        <div class="xm-metric-label">Notional Value</div>
        <div class="xm-metric-value text-lg">${{ todayStats.totalValue.toLocaleString() }}</div>
      </XmCard>
    </div>

    <!-- Recent Alerts -->
    <XmCard v-if="execStore.alerts.length > 0" title="System Alerts">
      <div class="space-y-2">
        <div
          v-for="alert in execStore.alerts.slice(0, 5)"
          :key="alert.id"
          class="flex items-start gap-3 p-3 rounded-lg border"
          :class="alert.severity === 'CRITICAL' ? 'border-risk-red/30 bg-loss-bg' : 'border-xm-border-light bg-xm-bg-surface'"
        >
          <XmStatusDot :status="alert.severity === 'CRITICAL' ? 'red' : 'yellow'" />
          <div class="flex-1 min-w-0">
            <p class="text-sm text-xm-text-primary">{{ alert.message }}</p>
            <p class="text-xxs text-xm-text-tertiary mt-0.5">
              {{ alert.source }} · {{ alert.timestamp }}
            </p>
          </div>
          <XmBadge :variant="alert.severity === 'CRITICAL' ? 'danger' : 'warning'">
            {{ alert.severity }}
          </XmBadge>
        </div>
      </div>
    </XmCard>

    <!-- Trade Log Timeline -->
    <XmCard title="Trade Log" subtitle="Real-time order timeline">
      <div class="space-y-0">
        <div
          v-for="(log, idx) in tradeLogs"
          :key="log.id"
          class="flex items-center gap-4 py-3 px-4 border-b border-xm-border-light last:border-0 hover:bg-xm-bg-surface/50 transition-colors"
        >
          <!-- Timeline dot -->
          <div class="flex-shrink-0 flex flex-col items-center">
            <span class="w-2.5 h-2.5 rounded-full" :class="{
              'bg-profit': log.status === 'filled',
              'bg-risk-yellow': log.status === 'partial',
              'bg-risk-red': log.status === 'rejected',
              'bg-xm-border': log.status === 'pending',
            }" />
            <div v-if="idx < tradeLogs.length - 1" class="w-px h-8 bg-xm-border-light mt-1" />
          </div>

          <!-- Content -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-sm font-mono font-semibold">{{ log.ticker }}</span>
              <XmBadge :variant="log.side === 'buy' ? 'success' : 'danger'">
                {{ log.side.toUpperCase() }}
              </XmBadge>
              <XmBadge :variant="statusBadge(log.status) as any">{{ log.status }}</XmBadge>
              <span class="text-xs text-xm-text-tertiary font-mono ml-auto">{{ log.timestamp }}</span>
            </div>
            <div class="flex items-center gap-4 mt-1">
              <span class="text-xs text-xm-text-secondary">
                {{ log.quantity }} shares @ ${{ log.price.toFixed(2) }}
              </span>
              <span class="text-xs font-mono text-xm-text-secondary">
                Value: ${{ log.value.toLocaleString() }}
              </span>
              <span class="text-xs text-xm-text-tertiary">{{ log.algo }}</span>
            </div>
          </div>
        </div>
      </div>
    </XmCard>
  </div>
</template>
