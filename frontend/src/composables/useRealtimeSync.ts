/** Realtime WebSocket sync: Tiger snapshot + cycle data → Pinia stores. */

import { ref, onMounted, onUnmounted } from 'vue'
import { usePortfolioStore } from '@/stores/usePortfolioStore'
import { useExecutionStore } from '@/stores/useExecutionStore'
import { useDataStore } from '@/stores/useDataStore'
import { executionApi } from '@/api/executionApi'

export type WsStatus = 'disconnected' | 'connecting' | 'connected'

const wsStatus = ref<WsStatus>('disconnected')
const lastTigerAt = ref<string>('')
const lastCycleAt = ref<string>('')

let socket: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | undefined
let pingTimer: ReturnType<typeof setInterval> | undefined
let started = false
let intentionalClose = false

function wsUrl(): string {
  const custom = import.meta.env.VITE_WS_URL
  if (custom) return custom
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws?room=tiger,market-data`
}

function applySnapshot(msg: Record<string, unknown>) {
  const portfolio = usePortfolioStore()
  const exec = useExecutionStore()
  const data = useDataStore()
  portfolio.applyTigerSnapshot(msg)
  const orders = msg.orders as Array<Record<string, unknown>> | undefined
  exec.applyTigerOrders(orders)
  data.applyTigerOrders(orders)
  lastTigerAt.value = new Date().toISOString()
}

function handleMessage(raw: string) {
  let msg: Record<string, unknown>
  try {
    msg = JSON.parse(raw) as Record<string, unknown>
  } catch {
    return
  }

  const type = String(msg.type || '')
  const exec = useExecutionStore()

  if (type === 'tiger_snapshot' || msg.source === 'tiger' || msg.source === 'local_paper' || Array.isArray(msg.positions)) {
    if (type === 'tiger_snapshot' || msg.source === 'tiger' || msg.source === 'local_paper' || msg.nav != null) {
      applySnapshot(msg)
      return
    }
  }

  if (type === 'cycle_summary' || type === 'step_update' || type === 'alert') {
    exec.applyCyclePush(msg)
    lastCycleAt.value = new Date().toISOString()
  }
}

async function hydrateFromHttp() {
  const portfolio = usePortfolioStore()
  const exec = useExecutionStore()
  const data = useDataStore()
  try {
    const snap = await executionApi.getTigerSnapshot()
    if (snap && typeof snap === 'object') {
      applySnapshot(snap)
    }
  } catch {
    /* snapshot endpoint may 404 on older backends */
  }
  await Promise.allSettled([
    portfolio.fetchPositions(),
    portfolio.fetchTigerAccount(),
    exec.fetchOrders(),
    data.fetchOrders({ limit: 50 }),
  ])
}

function clearTimers() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = undefined
  }
  if (pingTimer) {
    clearInterval(pingTimer)
    pingTimer = undefined
  }
}

function connect() {
  if (intentionalClose) return
  clearTimers()
  wsStatus.value = 'connecting'
  try {
    socket = new WebSocket(wsUrl())
  } catch {
    wsStatus.value = 'disconnected'
    scheduleReconnect()
    return
  }

  socket.onopen = () => {
    wsStatus.value = 'connected'
    void hydrateFromHttp()
    pingTimer = setInterval(() => {
      if (socket?.readyState === WebSocket.OPEN) socket.send('ping')
    }, 25000)
  }

  socket.onmessage = (ev) => {
    if (typeof ev.data === 'string' && ev.data !== 'pong') {
      handleMessage(ev.data)
    }
  }

  socket.onerror = () => {
    // onclose will schedule reconnect
  }

  socket.onclose = () => {
    wsStatus.value = 'disconnected'
    clearTimers()
    socket = null
    if (!intentionalClose) scheduleReconnect()
  }
}

function scheduleReconnect() {
  if (intentionalClose) return
  reconnectTimer = setTimeout(connect, 3000)
}

export function startRealtimeSync() {
  if (started) return
  started = true
  intentionalClose = false
  void hydrateFromHttp()
  connect()
}

export function stopRealtimeSync() {
  intentionalClose = true
  started = false
  clearTimers()
  if (socket) {
    try {
      socket.close()
    } catch {
      /* ignore */
    }
    socket = null
  }
  wsStatus.value = 'disconnected'
}

/** Vue helper: auto start/stop with component lifecycle. */
export function useRealtimeSync() {
  onMounted(() => startRealtimeSync())
  onUnmounted(() => {
    // Keep connection alive across page navigations — only stop on full unmount of root.
  })
  return { wsStatus, lastTigerAt, lastCycleAt, startRealtimeSync, stopRealtimeSync }
}

export { wsStatus, lastTigerAt, lastCycleAt }
