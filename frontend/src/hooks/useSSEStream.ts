/** 手写 SSE（30.12）— fetch+ReadableStream；双格式 JSON|SSE；≤100 行。 */
import { useCallback, useRef } from 'react'
import { apiFetch } from '@/api/http'
import { consumeSSEBuffer, type SSEHandlers } from '@/hooks/sseParse'

export type { SSEHandlers }
export { consumeSSEBuffer, dispatchSSEData } from '@/hooks/sseParse'

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
          const body = (await res.json()) as { response?: string } & Record<string, unknown>
          if (body.response) h.onToken?.(body.response)
          h.onDone?.(body)
          return
        }
        if (!res.body) return h.onError?.('SYS_001', 'empty_body')
        const reader = res.body.getReader()
        const dec = new TextDecoder()
        let buf = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buf += dec.decode(value, { stream: true })
          const out = consumeSSEBuffer(buf, h)
          buf = out.rest
          if (out.stopped) {
            await reader.cancel().catch(() => undefined)
            break
          }
        }
        if (buf.trim()) consumeSSEBuffer(`${buf}\n\n`, h)
      } catch (e) {
        if ((e as Error)?.name === 'AbortError') return
        h.onError?.('SYS_001', e instanceof Error ? e.message : String(e))
      } finally {
        if (abortRef.current === ac) abortRef.current = null
      }
    },
    [abort],
  )
  return { start, abort }
}
