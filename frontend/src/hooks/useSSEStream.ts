/** 手写 SSE（30.12）— fetch+ReadableStream；双格式 JSON|SSE；≤100 行。 */
import { useCallback, useRef } from 'react'
import { apiFetch } from '@/api/http'
import { createEventParser, type SSEHandlers } from '@/hooks/sseParse'

export type { SSEHandlers }
export { createEventParser, dispatchSSEData } from '@/hooks/sseParse'

export function useSSEStream() {
  const abortRef = useRef<AbortController | null>(null)
  const abort = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
  }, [])
  const start = useCallback(
    async (url: string, init: RequestInit, h: SSEHandlers) => {
      abort()
      const ac = new AbortController()
      abortRef.current = ac
      try {
        const res = await apiFetch(url, { ...init, signal: ac.signal })
        const ct = (res.headers.get('content-type') || '').toLowerCase()
        if (ct.includes('application/json')) {
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
        if (!res.body) return h.onError?.('SYS_001', 'empty_body')
        const reader = res.body.getReader()
        const dec = new TextDecoder()
        const parser = createEventParser(h)
        for (;;) {
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
          h.onAbort?.('client_abort')
          return
        }
        h.onError?.('SYS_001', e instanceof Error ? e.message : String(e))
      } finally {
        if (abortRef.current === ac) abortRef.current = null
      }
    },
    [abort],
  )
  return { start, abort }
}
