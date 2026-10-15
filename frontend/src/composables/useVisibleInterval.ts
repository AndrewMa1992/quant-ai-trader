import { onMounted, onUnmounted } from 'vue'

/**
 * Interval that runs only while the browser tab is visible.
 * Hidden tabs skip the callback so background pages do not keep polling.
 */
export function useVisibleInterval(callback: () => void, intervalMs: number) {
  let timer: ReturnType<typeof setInterval> | undefined
  let armed = false

  function clearTimer() {
    if (timer) clearInterval(timer)
    timer = undefined
  }

  function stop() {
    armed = false
    clearTimer()
  }

  function start() {
    armed = true
    clearTimer()
    if (document.hidden) return
    timer = setInterval(callback, intervalMs)
  }

  function onVisibilityChange() {
    if (!armed) return
    if (document.hidden) clearTimer()
    else start()
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', onVisibilityChange)
  })

  onUnmounted(() => {
    stop()
    document.removeEventListener('visibilitychange', onVisibilityChange)
  })

  return { start, stop }
}
