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
    fetchSyncStatus,
    fetchStoredTickers,
    triggerSync,
  }
})
