/** Realtime WebSocket sync: Tiger snapshot + cycle data → Pinia stores. */

import { ref, onMounted, onUnmounted } from 'vue'
import { usePortfolioStore } from '@/stores/usePortfolioStore'
import { useExecutionStore } from '@/stores/useExecutionStore'

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
  const custom = import.meta.env.VITE_WS_URL as string | undefined
  if (custom) return custom
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws?room=tiger,market-data`
}

function handleMessage(raw: string) {
  let msg: Record<string, unknown>
  try {
    msg = JSON.parse(raw) as Record<string, unknown>
  } catch {
    return
  }

  const type = String(msg.type || '')
  const portfolio = usePortfolioStore()
  const exec = useExecutionStore()

  if (type === 'tiger_snapshot' || msg.source === 'tiger' || msg.source === 'local_paper' || Array.isArray(msg.positions)) {
    if (type === 'tiger_snapshot' || msg.source === 'tiger' || msg.source === 'local_paper' || msg.nav != null) {
      portfolio.applyTigerSnapshot(msg)
      lastTigerAt.value = new Date().toISOString()
      return
    }
  }

  if (type === 'cycle_summary' || type === 'step_update' || type === 'alert') {
    exec.applyCyclePush(msg)
    lastCycleAt.value = new Date().toISOString()
  }
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
