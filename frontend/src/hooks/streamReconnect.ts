/**
 * Poll run snapshot after SSE disconnect (Task 63 slice 3).
 * Last-Event-ID resume is not implemented server-side — align UI via snapshot API.
 */
import { ApiError } from '@/api/http'
import { fetchRunSnapshot } from '@/api/chat'
import {
  applyExecutionEvent,
  executionFromSnapshot,
  type ExecutionState,
} from '@/hooks/sseParse'

const BACKOFF_MS = [1000, 2000, 4000, 8000, 8000]

export type ReconnectResult = 'complete' | 'not_found' | 'timeout' | 'cancelled'

function replayEvents(
  prev: ExecutionState | null,
  events: Record<string, unknown>[],
  afterSeq: number,
): ExecutionState | null {
  let state = prev
  for (const ev of events) {
    const seq = Number(ev.seq || 0)
    if (seq <= afterSeq) continue
    const type = String(ev.type || '')
    const payload = (ev.payload as Record<string, unknown> | undefined) ?? {}
    state = applyExecutionEvent(state, { type, ...payload })
  }
  return state
}

function isTerminalSnapshot(state: ExecutionState | null): boolean {
  if (!state?.steps.length) return false
  return state.steps.every(
    (s) => s.status === 'succeeded' || s.status === 'failed' || s.status === 'skipped',
  )
}

export async function pollRunSnapshot(opts: {
  traceId: string
  lastSeq?: number
  onProgress: (state: ExecutionState) => void
  signal?: AbortSignal
}): Promise<{ result: ReconnectResult; state: ExecutionState | null }> {
  const { traceId, onProgress, signal } = opts
  let lastSeq = opts.lastSeq ?? 0
  let latest: ExecutionState | null = null

  for (let attempt = 0; attempt < BACKOFF_MS.length; attempt += 1) {
    if (signal?.aborted) return { result: 'timeout', state: latest }
    await new Promise((r) => setTimeout(r, BACKOFF_MS[attempt]))
    if (signal?.aborted) return { result: 'timeout', state: latest }

    try {
      const body = await fetchRunSnapshot(traceId)
      const snap = body.snapshot as Record<string, unknown>
      latest = executionFromSnapshot(snap, traceId)
      const events = Array.isArray(body.events) ? body.events : []
      latest = replayEvents(latest, events as Record<string, unknown>[], lastSeq)
      lastSeq = Number(body.latest_seq || lastSeq)
      if (latest) onProgress(latest)

      const cancelled = events.some(
        (e) => String((e as Record<string, unknown>).type) === 'cancelled',
      )
      if (cancelled) return { result: 'cancelled', state: latest }

      if (isTerminalSnapshot(latest)) return { result: 'complete', state: latest }
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        return { result: 'not_found', state: latest }
      }
    }
  }
  return { result: 'timeout', state: latest }
}
