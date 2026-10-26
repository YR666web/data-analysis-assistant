// REST 封装（开发期经 Vite 代理转发到 FastAPI）

async function readResponse(res) {
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || data.error || `请求失败 (${res.status})`)
  return data
}

export async function submitTask(query, threadId, requirePdf = false) {
  const res = await fetch('/api/task', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, thread_id: threadId, require_pdf: requirePdf }),
  })
  return readResponse(res)
}

export async function cancelTask(threadId) {
  const res = await fetch(`/api/task/${encodeURIComponent(threadId)}/cancel`, { method: 'POST' })
  return readResponse(res)
}

export async function deleteSessionRemote(threadId) {
  const res = await fetch(`/api/session/${encodeURIComponent(threadId)}`, { method: 'DELETE' })
  return readResponse(res)
}

export async function getTaskStatus(threadId) {
  const res = await fetch(`/api/task/${encodeURIComponent(threadId)}`, {
    cache: 'no-store',
    signal: AbortSignal.timeout(8000),
  })
  return readResponse(res)
}

export async function getSavedSessions(offset = 0) {
  return readResponse(await fetch(`/api/sessions?offset=${offset}`, {
    cache: 'no-store', signal: AbortSignal.timeout(8000),
  }))
}

export async function uploadFiles(threadId, files) {
  const form = new FormData()
  form.append('thread_id', threadId)
  for (const f of files) form.append('files', f)
  const res = await fetch('/api/upload', { method: 'POST', body: form })
  return readResponse(res)
}

export async function listFiles(threadId, path) {
  const params = new URLSearchParams({ thread_id: threadId, path })
  return readResponse(await fetch(`/api/files?${params}`))
}

export async function downloadFile(threadId, path) {
  const params = new URLSearchParams({ thread_id: threadId, path })
  const res = await fetch(`/api/download?${params}`)
  if (!res.ok) throw new Error(`下载失败 (${res.status})`)
  return res
}

// WebSocket 连接（开发期经 Vite 代理 /ws 到后端）
export function connectWS(threadId, onEvent, { onClose = () => {}, signal } = {}) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${location.host}/ws/${encodeURIComponent(threadId)}`)
  let heartbeat
  let timer
  let lastMessage = Date.now()
  const abort = () => ws.close()
  const cleanup = () => {
    clearTimeout(timer)
    clearInterval(heartbeat)
    signal?.removeEventListener('abort', abort)
  }
  const ready = new Promise((resolve, reject) => {
    timer = setTimeout(() => {
      ws.close()
      reject(new Error('实时连接超时'))
    }, 3000)
    ws.onopen = () => {
      clearTimeout(timer)
      lastMessage = Date.now()
      heartbeat = setInterval(() => {
        if (Date.now() - lastMessage > 35000) ws.close()
        else if (ws.readyState === WebSocket.OPEN) ws.send('ping')
      }, 15000)
      resolve(ws)
    }
    ws.onerror = () => {
      cleanup()
      ws.close()
      reject(new Error('实时连接失败'))
    }
    ws.onclose = () => {
      cleanup()
      reject(new Error('实时连接已断开'))
      onClose()
    }
  })
  ws.onmessage = (e) => {
    lastMessage = Date.now()
    let data
    try {
      data = JSON.parse(e.data)
    } catch {
      return
    }
    if (data.type === 'monitor_event') onEvent(data)
  }
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) abort()
  return ready
}
