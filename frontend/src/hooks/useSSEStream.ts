/** 手写 SSE（30.12）— fetch+ReadableStream；双格式 JSON|SSE；≤100 行。 */
import { useCallback, useRef } from 'react'
import { apiFetch } from '@/api/http'
import { createEventParser, STREAM_ERROR, type SSEHandlers } from '@/hooks/sseParse'

export type { SSEHandlers }
export { createEventParser, dispatchSSEData } from '@/hooks/sseParse'

/**
 * useSSEStream
 *
 * Task 94 S3：新增 idle watchdog（字节级，默认关闭）。只有 chat 流式显式开启
 * （服务端 :ping 15s 一发，>50s 无字节 = 静默断网/挂死）；capability 等无 ping
 * 的 frame 端点不开，避免长静默帧间隔被误杀。watchdog 触发后本地 abort 连接并
 * 按「网络错误」语义上抛（onNetworkError）→ 触发断线续传轮询；与用户主动
 * abort() 区分：后者仍走 onAbort（本地止血），不误入续传路径。
 */
export function useSSEStream(opts?: { idleTimeoutMs?: number }) {
  const idleTimeoutMs = Math.max(0, opts?.idleTimeoutMs ?? 0)
  const abortRef = useRef<AbortController | null>(null)
  const idleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const watchdogFiredRef = useRef(false)

  const clearIdleTimer = useCallback(() => {
    if (idleTimerRef.current) {
      clearTimeout(idleTimerRef.current)
      idleTimerRef.current = null
    }
  }, [])

  const abort = useCallback(() => {
    clearIdleTimer()
    abortRef.current?.abort()
    abortRef.current = null
  }, [clearIdleTimer])

  const start = useCallback(
    async (url: string, init: RequestInit, h: SSEHandlers) => {
      abort()
      watchdogFiredRef.current = false
      const ac = new AbortController()
      abortRef.current = ac

      // 每次有字节到达即重排：watchdog 从「最后字节」起算（服务端 ping 也算字节）
      const armIdle = () => {
        clearIdleTimer()
        if (idleTimeoutMs <= 0 || ac.signal.aborted) return
        idleTimerRef.current = setTimeout(() => {
          watchdogFiredRef.current = true
          ac.abort()
        }, idleTimeoutMs)
      }

      try {
        armIdle()
        const res = await apiFetch(url, { ...init, signal: ac.signal })
        const traceHeader = res.headers.get('X-Trace-Id')
        if (traceHeader) h.onTraceId?.(traceHeader.trim())
        const ct = (res.headers.get('content-type') || '').toLowerCase()
        if (ct.includes('application/json')) {
          clearIdleTimer()
          const body = (await res.json()) as {
            response?: string
            type?: string
            code?: string
            message?: string
          } & Record<string, unknown>
          // Pre-stream errors (e.g. LLM_KEY_*) return JSON 400 — not a short-path success
          if (!res.ok || body.type === 'error') {
            h.onError?.(
              String(body.code || 'SYS_001'),
              String(body.message || `http_${res.status}`),
            )
            return
          }
          if (body.response) h.onToken?.(body.response)
          h.onDone?.({ ...body, path: 'short', contentType: 'application/json' })
          return
        }
        if (!res.body) {
          clearIdleTimer()
          h.onError?.('SYS_001', 'empty_body')
          return
        }
        const reader = res.body.getReader()
        const dec = new TextDecoder()
        const parser = createEventParser(h)
        for (;;) {
          armIdle()
          const { done, value } = await reader.read()
          if (done) break
          parser.feed(dec.decode(value, { stream: true }))
          if (parser.stopped()) {
            await reader.cancel().catch(() => undefined)
            break
          }
        }
      } catch (e) {
        if ((e as Error)?.name === 'AbortError') {
          if (watchdogFiredRef.current) {
            // 静默断网/挂死：本地按网络错误上抛 → 走断线续传路径
            if (h.onNetworkError) {
              h.onNetworkError(new Error('idle_timeout'))
              return
            }
            h.onError?.(STREAM_ERROR.NET_DISCONNECT, '连接空闲超时')
            return
          }
          h.onAbort?.('client_abort')
          return
        }
        const err = e instanceof Error ? e : new Error(String(e))
        if (h.onNetworkError) {
          h.onNetworkError(err)
          return
        }
        h.onError?.('SYS_001', err.message)
      } finally {
        clearIdleTimer()
        if (abortRef.current === ac) abortRef.current = null
      }
    },
    [abort, clearIdleTimer, idleTimeoutMs],
  )
  return { start, abort }
}
