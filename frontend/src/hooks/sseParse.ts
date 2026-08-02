/** SSE 帧解析纯函数（useSSEStream 配套）。 */
export type SSEHandlers = {
  onToken?: (text: string) => void
  onAbort?: (reason: string) => void
  onRetraction?: (reason: string) => void
  onError?: (code: string, message: string) => void
  onDone?: (meta?: Record<string, unknown>) => void
}

export function dispatchSSEData(raw: string, h: SSEHandlers): 'done' | 'continue' {
  const text = raw.trim()
  if (!text) return 'continue'
  if (text === '[DONE]') {
    h.onDone?.({ path: 'long' })
    return 'done'
  }
  let obj: Record<string, unknown>
  try {
    obj = JSON.parse(text) as Record<string, unknown>
  } catch {
    return 'continue'
  }
  if (typeof obj.token === 'string') {
    h.onToken?.(obj.token)
    return 'continue'
  }
  const t = String(obj.type || '')
  if (t === 'abort') {
    h.onAbort?.(String(obj.reason || 'abort'))
    return 'done'
  }
  if (t === 'retraction') {
    h.onRetraction?.(String(obj.reason || 'retraction'))
    return 'continue'
  }
  if (t === 'error') {
    h.onError?.(String(obj.code || 'SYS_001'), String(obj.message || 'error'))
    return 'done'
  }
  if (t === 'done') {
    h.onDone?.({ ...obj, path: 'long' })
    return 'done'
  }
  return 'continue'
}

export function consumeSSEBuffer(buffer: string, h: SSEHandlers) {
  const parts = buffer.split('\n\n')
  const rest = parts.pop() ?? ''
  for (const block of parts) {
    for (const line of block.split('\n')) {
      const s = line.trimEnd()
      if (!s || s.startsWith(':')) continue // : ping
      if (!s.startsWith('data:')) continue
      if (dispatchSSEData(s.slice(5).trimStart(), h) === 'done') {
        return { rest: '', stopped: true as const }
      }
    }
  }
  return { rest, stopped: false as const }
}
