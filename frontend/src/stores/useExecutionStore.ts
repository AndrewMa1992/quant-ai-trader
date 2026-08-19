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

  /** Apply cycle / alert payloads from gateway WebSocket. */
  function applyCyclePush(msg: Record<string, unknown>) {
    const type = String(msg.type || '')
    if (type === 'alert') {
      alerts.value.unshift({
        id: `ws-${Date.now()}`,
        message: String(msg.message || ''),
        severity: String(msg.alert_type || msg.severity || 'info'),
        source: 'ws',
        timestamp: new Date().toISOString(),
      })
      if (alerts.value.length > 100) alerts.value = alerts.value.slice(0, 100)
      return
    }
    const data = (msg.data as Record<string, unknown> | undefined) || msg
    const maybeOrders = data.orders
    if (Array.isArray(maybeOrders)) {
      for (const o of maybeOrders as Array<Record<string, unknown>>) {
        const oid = String(o.order_id || '')
        if (!oid) continue
        if (orders.value.some((x) => x.order_id === oid)) continue
        orders.value.unshift({
          order_id: oid,
          ticker: String(o.ticker || ''),
          side: String(o.side || ''),
          quantity: Number(o.quantity || 0),
          status: String(o.status || 'FILLED'),
          timestamp: String(o.timestamp || o.filled_at || new Date().toISOString()),
        })
      }
      if (orders.value.length > 200) orders.value = orders.value.slice(0, 200)
    }
  }

  async function rollback(): Promise<{ success: boolean; message: string; timestamp: string } | null> {
    try {
      const result = await executionApi.rollback()
      cbStatus.value = { halted: false, halt_reason: '', consecutive_losses: 0, cooling_active: false }
      return result
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Rollback failed'
      return null
    }
  }

  return {
    orders, alerts, marketStatus, cbStatus, loading, error,
    fetchAlerts, fetchMarketStatus, placeOrder, setCBStatus, applyCyclePush, rollback,
  }
})
