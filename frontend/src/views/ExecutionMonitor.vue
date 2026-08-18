<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import XmCard from '@/components/ui/XmCard.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import XmStatusDot from '@/components/ui/XmStatusDot.vue'
import OrderSliceProgress from '@/components/execution/OrderSliceProgress.vue'
import { useExecutionStore } from '@/stores/useExecutionStore'
import { executionApi } from '@/api/executionApi'
import { tradeApi, type TradeRecord } from '@/api/tradeApi'

const execStore = useExecutionStore()

interface OrderRow {
  id: string
  ticker: string
  side: string
  quantity: number
  filled: number
  price: number
  value: number
  status: string
  timestamp: string
  algo: string
  slices?: Array<{ label: string; completed: number; total: number; status: 'pending' | 'executing' | 'filled' }>
}

const orders = ref<OrderRow[]>([])
const sideFilter = ref('all')
const statusFilter = ref('all')
const loading = ref(false)
const selectedOrderId = ref<string | null>(null)

const filteredOrders = computed(() => {
  return orders.value.filter((o) => {
    if (sideFilter.value !== 'all' && o.side.toLowerCase() !== sideFilter.value) return false
    if (statusFilter.value !== 'all' && o.status.toLowerCase() !== statusFilter.value) return false
    return true
  })
})

const todayStats = computed(() => {
  const filled = orders.value.filter((t) => t.status === 'filled' || t.status === 'partial')
  const buys = filled.filter((t) => t.side === 'buy')
  const sells = filled.filter((t) => t.side === 'sell')
  const totalValue = filled.reduce((s, t) => s + t.value, 0)
  return {
    totalTrades: filled.length,
    buyCount: buys.length,
    sellCount: sells.length,
    totalValue,
    rejectedCount: orders.value.filter((t) => t.status === 'rejected').length,
  }
})

const selectedSlices = computed(() => {
  const order = orders.value.find((o) => o.id === selectedOrderId.value)
  if (!order) return []
  if (order.slices && order.slices.length > 0) return order.slices
  // Fallback progress from filled/qty
  const filled = order.filled || (order.status === 'filled' ? order.quantity : 0)
  const status: 'pending' | 'executing' | 'filled' =
    order.status === 'filled' ? 'filled' : filled > 0 ? 'executing' : 'pending'
  return [{
    label: order.ticker,
    completed: filled,
    total: Math.max(order.quantity, 1),
    status,
  }]
})

onMounted(async () => {
  await Promise.all([
    execStore.fetchAlerts(),
    fetchOrders(),
  ])
})

async function fetchOrders(): Promise<void> {
  loading.value = true
  try {
    // Prefer execution API orders
    try {
      const data = await executionApi.getTradeLogs()
      const raw = (data?.orders ?? data ?? []) as Array<Record<string, unknown>>
      if (Array.isArray(raw) && raw.length > 0) {
        orders.value = raw.map(mapOrder)
        return
      }
    } catch {
      // fall through
    }

    const result = await tradeApi.getTradeHistory(50)
    const trades: TradeRecord[] = result.trades ?? []
    orders.value = trades.map((t) => ({
      id: `T-${String(t.id)}`,
      ticker: t.ticker,
      side: String(t.side || '').toLowerCase(),
      quantity: t.quantity,
      filled: t.status === 'filled' ? t.quantity : 0,
      price: t.price,
      value: t.value ?? t.quantity * t.price,
      status: String(t.status ?? 'filled').toLowerCase(),
      timestamp: t.timestamp,
      algo: t.strategy ?? 'TWAP',
    }))
  } catch {
    orders.value = []
  } finally {
    loading.value = false
  }
}

function mapOrder(t: Record<string, unknown>): OrderRow {
  const qty = Number(t.quantity ?? t.qty ?? 0)
  const filled = Number(t.filled ?? t.filled_qty ?? (String(t.status).toLowerCase() === 'filled' ? qty : 0))
  const price = Number(t.price ?? t.avg_price ?? 0)
  const slicesRaw = t.slices as Array<Record<string, unknown>> | undefined
  const slices = Array.isArray(slicesRaw)
    ? slicesRaw.map((s, i) => ({
        label: String(s.label ?? `S${i + 1}`),
        completed: Number(s.completed ?? s.filled ?? 0),
        total: Number(s.total ?? s.quantity ?? 1),
        status: (String(s.status || 'pending') as 'pending' | 'executing' | 'filled'),
      }))
    : undefined

  return {
    id: String(t.order_id ?? t.id ?? `O-${Math.random().toString(36).slice(2, 8)}`),
    ticker: String(t.ticker ?? ''),
    side: String(t.side ?? '').toLowerCase(),
    quantity: qty,
    filled,
    price,
    value: Number(t.value ?? qty * price),
    status: String(t.status ?? 'unknown').toLowerCase(),
    timestamp: String(t.timestamp ?? t.created_at ?? ''),
    algo: String(t.algo ?? t.strategy ?? 'TWAP'),
    slices,
  }
}

function statusBadge(status: string): string {
  switch (status) {
    case 'filled': return 'success'
    case 'partial': return 'warning'
    case 'rejected': return 'danger'
    default: return 'info'
  }
}

function fillPct(order: OrderRow): number {
  if (order.quantity <= 0) return 0
  const filled = order.filled || (order.status === 'filled' ? order.quantity : 0)
  return Math.min(100, (filled / order.quantity) * 100)
}
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <XmCard class="!p-4">
        <div class="xm-metric-label">Orders</div>
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

    <XmCard title="System Alerts">
      <div v-if="execStore.alerts.length === 0" class="text-center py-6 text-xm-text-tertiary text-sm">
        No active alerts.
      </div>
      <div v-else class="space-y-2">
        <div
          v-for="alert in execStore.alerts.slice(0, 8)"
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

    <XmCard title="Orders" subtitle="Filter by side / status">
      <div class="flex flex-wrap items-end gap-3 mb-4">
        <div class="w-[140px]">
          <label class="block text-xxs text-xm-text-tertiary mb-1">Side</label>
          <select v-model="sideFilter" class="xm-input w-full">
            <option value="all">All</option>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
        </div>
        <div class="w-[160px]">
          <label class="block text-xxs text-xm-text-tertiary mb-1">Status</label>
          <select v-model="statusFilter" class="xm-input w-full">
            <option value="all">All</option>
            <option value="filled">Filled</option>
            <option value="partial">Partial</option>
            <option value="pending">Pending</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>
        <button class="xm-btn-secondary" :disabled="loading" @click="fetchOrders">
          {{ loading ? 'Loading...' : 'Refresh' }}
        </button>
      </div>

      <div v-if="loading" class="text-center py-10 text-xm-text-tertiary text-sm">Loading orders...</div>
      <div v-else-if="filteredOrders.length === 0" class="text-center py-10 text-xm-text-tertiary text-sm">
        No orders match the current filters.
      </div>
      <table v-else class="xm-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Ticker</th>
            <th>Side</th>
            <th class="text-right">Qty</th>
            <th class="text-right">Filled</th>
            <th>Progress</th>
            <th>Status</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="log in filteredOrders"
            :key="log.id"
            class="cursor-pointer"
            :class="{ 'bg-xm-primary-light/40': selectedOrderId === log.id }"
            @click="selectedOrderId = log.id"
          >
            <td class="font-mono text-xs">{{ log.id }}</td>
            <td class="font-mono font-semibold">{{ log.ticker }}</td>
            <td>
              <XmBadge :variant="log.side === 'buy' ? 'success' : 'danger'">
                {{ log.side.toUpperCase() }}
              </XmBadge>
            </td>
            <td class="text-right font-mono">{{ log.quantity }}</td>
            <td class="text-right font-mono">{{ log.filled }}</td>
            <td class="min-w-[100px]">
              <div class="w-full h-1.5 bg-xm-bg-surface rounded-full overflow-hidden">
                <div
                  class="h-full rounded-full"
                  style="background-color: #FF6700"
                  :style="{ width: fillPct(log) + '%' }"
                />
              </div>
            </td>
            <td>
              <XmBadge :variant="statusBadge(log.status) as any">{{ log.status }}</XmBadge>
            </td>
            <td class="text-xs text-xm-text-tertiary">{{ log.timestamp }}</td>
          </tr>
        </tbody>
      </table>
    </XmCard>

    <XmCard v-if="selectedOrderId" title="Order Slice Progress">
      <OrderSliceProgress :slices="selectedSlices" />
    </XmCard>
  </div>
</template>
