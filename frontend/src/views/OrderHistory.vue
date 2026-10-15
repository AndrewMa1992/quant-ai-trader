<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import XmCard from '@/components/ui/XmCard.vue'
import XmBadge from '@/components/ui/XmBadge.vue'
import { useDataStore } from '@/stores/useDataStore'
import type { BadgeVariant } from '@/types/ui'

const dataStore = useDataStore()

const tickerFilter = ref('')
const statusFilter = ref('')
const limitFilter = ref(50)

const kpiOrders = computed(() => dataStore.orders.length)
const kpiFilled = computed(() => dataStore.filledOrders.length)
const kpiRejected = computed(() => dataStore.rejectedOrders.length)
const kpiPending = computed(() => dataStore.pendingOrders.length)

async function doSearch() {
  const params: { ticker?: string; status?: string; limit?: number } = { limit: limitFilter.value }
  if (tickerFilter.value.trim()) params.ticker = tickerFilter.value.trim().toUpperCase()
  if (statusFilter.value && statusFilter.value !== 'all') params.status = statusFilter.value
  await dataStore.fetchOrders(params)
}

function sideBadge(side: string): BadgeVariant {
  const s = (side || '').toLowerCase()
  if (s === 'buy') return 'success'
  if (s === 'sell') return 'danger'
  return 'info'
}

function statusBadge(status: string): BadgeVariant {
  const s = (status || '').toLowerCase()
  if (s === 'filled') return 'success'
  if (s === 'rejected') return 'danger'
  if (s === 'partial') return 'warning'
  return 'info'
}

function fmtDate(val?: string) {
  if (!val) return '-'
  try { return new Date(val).toLocaleString() } catch { return val }
}

function orderId(order: { order_id?: string; orderId?: string }) {
  return order.order_id || order.orderId || '-'
}

onMounted(() => {
  dataStore.fetchOrders({ limit: 50 })
})
</script>

<template>
  <div class="space-y-6 xm-fade-in">
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <XmCard class="!p-4">
        <div class="xm-metric-label">Total Orders</div>
        <div class="xm-metric-value text-lg">{{ kpiOrders }}</div>
      </XmCard>
      <XmCard class="!p-4">
        <div class="xm-metric-label">Filled</div>
        <div class="xm-metric-value text-lg text-profit">{{ kpiFilled }}</div>
      </XmCard>
      <XmCard class="!p-4">
        <div class="xm-metric-label">Rejected</div>
        <div class="xm-metric-value text-lg text-loss">{{ kpiRejected }}</div>
      </XmCard>
      <XmCard class="!p-4">
        <div class="xm-metric-label">Pending</div>
        <div class="xm-metric-value text-lg text-xm-text-secondary">{{ kpiPending }}</div>
      </XmCard>
    </div>

    <XmCard class="!p-4">
      <div class="flex flex-wrap items-end gap-3">
        <div class="flex-1 min-w-[140px]">
          <label class="block text-xxs text-xm-text-tertiary mb-1">Ticker</label>
          <input
            v-model="tickerFilter"
            placeholder="e.g. AAPL"
            class="xm-input w-full"
            @keyup.enter="doSearch"
          />
        </div>
        <div class="w-[160px]">
          <label class="block text-xxs text-xm-text-tertiary mb-1">Status</label>
          <select v-model="statusFilter" class="xm-input w-full">
            <option value="all">All</option>
            <option value="filled">Filled</option>
            <option value="rejected">Rejected</option>
            <option value="partial">Partial</option>
            <option value="pending">Pending</option>
          </select>
        </div>
        <div class="w-[100px]">
          <label class="block text-xxs text-xm-text-tertiary mb-1">Limit</label>
          <input v-model.number="limitFilter" type="number" min="1" max="500" class="xm-input w-full" />
        </div>
        <button class="xm-btn-primary" @click="doSearch">Search</button>
      </div>
    </XmCard>

    <XmCard title="Orders" :subtitle="`${dataStore.orders.length} records`">
      <div v-if="dataStore.loading" class="text-center py-10 text-xm-text-tertiary text-sm">
        Loading orders...
      </div>
      <table v-else-if="dataStore.orders.length > 0" class="xm-table">
        <thead>
          <tr>
            <th>Order ID</th>
            <th>Ticker</th>
            <th>Side</th>
            <th class="text-right">Quantity</th>
            <th class="text-right">Price</th>
            <th>Type</th>
            <th>Status</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(order, idx) in dataStore.orders" :key="orderId(order) + '-' + idx">
            <td class="font-mono text-xs">{{ orderId(order) }}</td>
            <td class="font-mono font-semibold">{{ order.ticker }}</td>
            <td>
              <XmBadge :variant="sideBadge(order.side)">{{ (order.side || '').toUpperCase() }}</XmBadge>
            </td>
            <td class="text-right font-mono">{{ order.quantity }}</td>
            <td class="text-right font-mono">{{ order.price ? '$' + order.price.toFixed(2) : '-' }}</td>
            <td class="text-xs">{{ order.order_type || order.strategy || '-' }}</td>
            <td>
              <XmBadge :variant="statusBadge(order.status)">{{ order.status }}</XmBadge>
            </td>
            <td class="text-xs text-xm-text-tertiary">{{ fmtDate(order.created_at || order.timestamp) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="text-center py-10 text-xm-text-tertiary text-sm">
        No orders found. Try adjusting your filters or ensure the execution API is reachable.
      </div>
    </XmCard>

    <div
      v-if="dataStore.error"
      class="p-3 rounded-lg bg-loss-bg border border-loss/20 text-sm text-loss"
    >
      {{ dataStore.error }}
    </div>
  </div>
</template>
