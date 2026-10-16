/** stores/useDataStore.ts – Data explorer + sync Pinia store (v2 syncApi) */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  syncApi,
  type OrderRecord,
  type SyncStatusRecord,
  type StorageStats,
} from '../api/syncApi'

export const useDataStore = defineStore('dataStore', () => {
  const orders = ref<OrderRecord[]>([])
  const syncStatuses = ref<SyncStatusRecord[]>([])
  const storageStats = ref<StorageStats>({})
  const storedTickers = ref<string[]>([])

  const loading = ref(false)
  const error = ref('')
  const syncInProgress = ref(false)

  const filledOrders = computed(() =>
    orders.value.filter((o) => String(o.status || '').toLowerCase() === 'filled'),
  )
  const rejectedOrders = computed(() =>
    orders.value.filter((o) => String(o.status || '').toLowerCase() === 'rejected'),
  )
  const pendingOrders = computed(() =>
    orders.value.filter((o) => {
      const s = String(o.status || '').toLowerCase()
      return s === 'pending' || s === 'partial' || s === 'submitted'
    }),
  )
  const syncErrorCount = computed(() =>
    syncStatuses.value.filter((s) => {
      const st = String(s.status || '').toLowerCase()
      return st === 'error' || st === 'empty'
    }).length,
  )

  function applyTigerOrders(raw: Array<Record<string, unknown>> | undefined) {
    if (!Array.isArray(raw) || raw.length === 0) return
    const mapped = raw.map((o) => ({
      order_id: String(o.order_id || o.orderId || o.id || ''),
      orderId: String(o.order_id || o.orderId || o.id || ''),
      ticker: String(o.ticker || o.symbol || ''),
      side: String(o.side || o.action || ''),
      quantity: Number(o.quantity || 0),
      price: Number(o.price || o.avg_fill_price || 0),
      status: String(o.status || 'SUBMITTED').replace(/^orderstatus\./i, ''),
      order_type: String(o.order_type || 'MKT'),
      created_at: String(o.submitted_at || o.created_at || ''),
      updated_at: String(o.updated_at || o.filled_at || ''),
      timestamp: String(o.timestamp || o.filled_at || o.submitted_at || ''),
      strategy: String(o.strategy || 'tiger'),
    }))
    const seen = new Set(orders.value.map((o) => String(o.order_id || o.orderId || '')))
    const incoming = mapped.filter((o) => {
      const id = o.order_id
      if (id && seen.has(id)) return false
      if (id) seen.add(id)
      return Boolean(o.ticker || o.order_id)
    })
    if (incoming.length) {
      orders.value = [...incoming, ...orders.value].slice(0, 200)
    }
  }

  async function fetchOrders(params?: { ticker?: string; status?: string; limit?: number }) {
    loading.value = true
    error.value = ''
    try {
      const result = await syncApi.getOrders(params)
      orders.value = result?.orders ?? []
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch orders'
      orders.value = []
    } finally {
      loading.value = false
    }
  }

  async function fetchSyncStatus() {
    try {
      const result = await syncApi.getSyncStatus()
      syncStatuses.value = result.sync_status ?? []
      storageStats.value = result.storage ?? {}
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch sync status'
      syncStatuses.value = []
    }
  }

  async function fetchStoredTickers() {
    try {
      storedTickers.value = (await syncApi.getStoredTickers()) ?? []
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch tickers'
      storedTickers.value = []
    }
  }

  async function triggerSync(force = false) {
    syncInProgress.value = true
    error.value = ''
    try {
      const result = await syncApi.triggerSync(force)
      await fetchSyncStatus()
      return result
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Sync trigger failed'
      return null
    } finally {
      syncInProgress.value = false
    }
  }

  return {
    orders,
    syncStatuses,
    storageStats,
    storedTickers,
    loading,
    error,
    syncInProgress,
    filledOrders,
    rejectedOrders,
    pendingOrders,
    syncErrorCount,
    fetchOrders,
    applyTigerOrders,
    fetchSyncStatus,
    fetchStoredTickers,
    triggerSync,
  }
})
