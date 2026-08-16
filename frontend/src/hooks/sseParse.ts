/**
 * SSE 事件分发（后端 /chat/streaming 协议）+ eventsource-parser 封装。
 *
 * 解析层用标准库 eventsource-parser（处理多行 data / CRLF / 帧边界），
 * dispatchSSEData 保留为后端协议适配（token/abort/retraction/error/done JSON）。
 */
import { createParser, type EventSourceMessage } from 'eventsource-parser'

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

export type SSEParserHandle = {
  feed: (chunk: string) => void
  stopped: () => boolean
}

/** 流式喂块；任一终态事件（abort/error/done）后 stopped() 为 true。 */
export function createEventParser(h: SSEHandlers): SSEParserHandle {
  let stopped = false
  const parser = createParser({
    onEvent(event: EventSourceMessage) {
      if (stopped) return
      if (dispatchSSEData(event.data, h) === 'done') stopped = true
    },
  })
  return {
    feed: (chunk: string) => {
      if (!stopped) parser.feed(chunk)
    },
    stopped: () => stopped,
  }
}
