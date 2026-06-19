/** stores/useDataStore.ts – Phase 5: Data management Pinia store */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { syncApi, type OrderRecord, type TransactionRecord, type FundamentalRecord, type CapitalFlowRecord, type CalendarRecord, type SyncStatusRecord } from '../api/syncApi'

export const useDataStore = defineStore('dataStore', () => {
  const orders = ref<OrderRecord[]>([])
  const transactions = ref<TransactionRecord[]>([])
  const fundamentals = ref<Record<string, FundamentalRecord>>({})
  const capitalFlows = ref<Record<string, CapitalFlowRecord[]>>({})
  const calendar = ref<CalendarRecord[]>([])
  const syncStatuses = ref<SyncStatusRecord[]>([])
  const rateLimiterStats = ref<Record<string, any>>({})

  const loading = ref(false)
  const error = ref('')
  const syncInProgress = ref(false)

  const filledOrders = computed(() => orders.value.filter(o => o.status === 'filled'))
  const rejectedOrders = computed(() => orders.value.filter(o => o.status === 'rejected'))
  const pendingOrders = computed(() => orders.value.filter(o => o.status === 'pending' || o.status === 'partial'))

  const tradingDays = computed(() => calendar.value.filter(c => c.is_trading_day))
  const syncErrorCount = computed(() => syncStatuses.value.filter(s => s.status === 'error').length)

  async function fetchOrders(params?: { ticker?: string; status?: string; limit?: number }) {
    loading.value = true; error.value = ''
    try {
      orders.value = (await syncApi.getOrders(params)) ?? []
    } catch (e: any) { error.value = e?.message || 'Failed to fetch orders' }
    finally { loading.value = false }
  }

  async function fetchTransactions(params?: { ticker?: string; limit?: number }) {
    loading.value = true; error.value = ''
    try {
      transactions.value = (await syncApi.getTransactions(params)) ?? []
    } catch (e: any) { error.value = e?.message || 'Failed to fetch transactions' }
    finally { loading.value = false }
  }

  async function fetchFundamentals(ticker: string) {
    try {
      const result = await syncApi.getFundamentals(ticker)
      if (result) fundamentals.value[ticker] = result
    } catch (e: any) { error.value = e?.message || `Failed to fetch fundamentals for ${ticker}` }
  }

  async function fetchCapitalFlow(ticker: string, params?: { start_date?: string; end_date?: string; limit?: number }) {
    loading.value = true; error.value = ''
    try {
      capitalFlows.value[ticker] = (await syncApi.getCapitalFlow(ticker, params)) ?? []
    } catch (e: any) { error.value = e?.message || `Failed to fetch capital flow for ${ticker}` }
    finally { loading.value = false }
  }

  async function fetchCalendar(params?: { market?: string; trading_only?: boolean }) {
    try {
      calendar.value = (await syncApi.getCalendar(params)) ?? []
    } catch (e: any) { error.value = e?.message || 'Failed to fetch calendar' }
  }

  async function fetchSyncStatus() {
    try {
      const result = await syncApi.getSyncStatus()
      syncStatuses.value = result.sync_status ?? []
      rateLimiterStats.value = result.rate_limiter ?? {}
    } catch (e: any) { error.value = e?.message || 'Failed to fetch sync status' }
  }

  async function triggerSync(force = false) {
    syncInProgress.value = true
    try {
      const result = await syncApi.triggerSync(force)
      await fetchSyncStatus()
      return result
    } catch (e: any) { error.value = e?.message || 'Sync trigger failed' }
    finally { syncInProgress.value = false }
  }

  return {
    orders, transactions, fundamentals, capitalFlows, calendar,
    syncStatuses, rateLimiterStats,
    loading, error, syncInProgress,
    filledOrders, rejectedOrders, pendingOrders,
    tradingDays, syncErrorCount,
    fetchOrders, fetchTransactions, fetchFundamentals, fetchCapitalFlow,
    fetchCalendar, fetchSyncStatus, triggerSync,
  }
})
