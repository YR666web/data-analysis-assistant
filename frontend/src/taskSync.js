import { connectWS, getTaskStatus } from './api.js'

// One controller per task. Connect before submission to catch fast events, but
// only poll after the POST is accepted (unknown before submission is expected).
export function createTaskSync(threadId, {
  onEvent, onState,
  connect = connectWS, getStatus = getTaskStatus,
  pollMs = 2000, retryMs = 1000,
}) {
  let stopped = false
  let started = false
  let socket = null
  let connecting = false
  let polling = false
  let pollTimer
  let retryTimer
  let retryDelay = retryMs
  const controller = new AbortController()

  function retry() {
    if (stopped || retryTimer) return
    retryTimer = setTimeout(() => {
      retryTimer = null
      open()
    }, retryDelay)
    retryDelay = Math.min(retryDelay * 2, 10000)
  }

  async function open() {
    if (stopped || connecting) return
    connecting = true
    try {
      const ws = await connect(threadId, (event) => {
        if (!stopped) onEvent(event)
      }, {
        signal: controller.signal,
        onClose: () => {
          socket = null
          retry()
        },
      })
      if (stopped) { ws.close(); return }
      socket = ws
      retryDelay = retryMs
      if (started) refresh()
    } catch {
      // A socket failure must not prevent POST submission or REST recovery.
      retry()
    } finally {
      connecting = false
    }
  }

  async function refresh() {
    if (stopped || !started || polling) return
    clearTimeout(pollTimer)
    polling = true
    try {
      const state = await getStatus(threadId)
      if (!stopped) onState(state)
    } catch {
      // Transient network failure leaves task state intact; retry automatically.
    } finally {
      polling = false
      if (!stopped) pollTimer = setTimeout(refresh, pollMs)
    }
  }

  return {
    ready: open(),
    start() { if (!stopped) { started = true; return refresh() } },
    refresh,
    stop() {
      stopped = true
      clearTimeout(pollTimer)
      clearTimeout(retryTimer)
      controller.abort()
      socket?.close()
      socket = null
    },
  }
}
