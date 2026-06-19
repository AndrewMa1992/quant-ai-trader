/** stores/useExecutionStore.ts – Execution data Pinia store */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { executionApi, type Alert } from '../api/executionApi'
import { dataApi, type MarketStatus } from '../api/dataApi'

export interface OrderRecord {
  order_id: string
  ticker: string
  side: string
  quantity: number
  status: string
  timestamp?: string
}

export const useExecutionStore = defineStore('execution', () => {
  const orders = ref<OrderRecord[]>([])
  const alerts = ref<Alert[]>([])
  const marketStatus = ref<MarketStatus>({})
  const cbStatus = ref({ halted: false, halt_reason: '', consecutive_losses: 0, cooling_active: false })
  const loading = ref(false)
  const error = ref('')

  async function fetchAlerts(severity = '') {
    try {
      const data = await executionApi.getAlerts(severity)
      alerts.value = data.alerts ?? []
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Alerts fetch failed'
    }
  }

  async function fetchMarketStatus() {
    try {
      marketStatus.value = await dataApi.getMarketStatus()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Market status failed'
    }
  }

  async function placeOrder(ticker: string, side: string, quantity: number, orderType = 'MKT', algo = 'twap') {
    try {
      const result = await executionApi.placeOrder(ticker, side, quantity, orderType, undefined, algo)
      orders.value.unshift({
        order_id: result.order_id ?? '',
        ticker,
        side,
        quantity,
        status: result.status ?? 'UNKNOWN',
        timestamp: new Date().toISOString(),
      })
      return result
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Order failed'
      return null
    }
  }

  function setCBStatus(status: typeof cbStatus.value) {
    cbStatus.value = status
  }

  return {
    orders, alerts, marketStatus, cbStatus, loading, error,
    fetchAlerts, fetchMarketStatus, placeOrder, setCBStatus,
  }
})
