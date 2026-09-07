/**
 * Poll run snapshot after SSE disconnect — Task 63 slice3 / Task 94 S3 poll v2.
 *
 * Task 94 语义分离后按 snapshot.status 分流：
 * - streaming → 续轮询（自适应节奏，直至接近服务端保温 TTL，不再 5 次 23s 就 timeout）
 * - completed → 按 assistant client_message_id 幂等回拉终态文本（终态回填）
 * - cancelled / failed → 对应终态
 * - 404（registry 终态窗已过）→ 降级按 client_message_id 查 DB 终态
 */
import { ApiError } from '@/api/http'
import {
  fetchAssistantMessageByClientId,
  fetchRunSnapshot,
  type RunSnapshotStatus,
} from '@/api/chat'
import {
  applyExecutionEvent,
  executionFromSnapshot,
  type ExecutionState,
} from '@/hooks/sseParse'

const POLL_START_MS = [1000, 2000]
const POLL_STEADY_MS = 3000
/** 服务端保温窗 RUN_WARM_TTL_S=600s；前端留 60s 余量，不无限轮询 */
const DEFAULT_MAX_WAIT_MS = 9 * 60 * 1000

export type ReconnectResult = 'complete' | 'not_found' | 'timeout' | 'cancelled' | 'failed'

export type PollRunSnapshotOpts = {
  traceId: string
  /** 断线丢的文本唯一可靠恢复 = 终态按 assistant cid 回拉（plan 拍板 #2） */
  assistantClientMessageId?: string
  lastSeq?: number
  onProgress?: (state: ExecutionState) => void
  signal?: AbortSignal
  maxWaitMs?: number
}

export type PollRunSnapshotResult = {
  result: ReconnectResult
  state: ExecutionState | null
  /** completed 且按 cid 查到 DB 终态文本时回填 */
  finalContent?: string
}

async function lookupFinalContent(cid?: string): Promise<string | undefined> {
  if (!cid) return undefined
  try {
    const lookup = await fetchAssistantMessageByClientId(cid)
    if (lookup.found && lookup.message?.content) {
      return lookup.message.content
    }
  } catch {
    // 回填失败不阻断恢复：调用方用本地部分文本兜底
  }
  return undefined
}

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

function terminalResult(status: RunSnapshotStatus): ReconnectResult | null {
  if (status === 'completed') return 'complete'
  if (status === 'cancelled') return 'cancelled'
  if (status === 'failed') return 'failed'
  return null
}

export async function pollRunSnapshot(opts: PollRunSnapshotOpts): Promise<PollRunSnapshotResult> {
  const { traceId, onProgress, signal } = opts
  const lastSeq = opts.lastSeq ?? 0
  const deadline = Date.now() + (opts.maxWaitMs ?? DEFAULT_MAX_WAIT_MS)
  const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
  let latest: ExecutionState | null = null
  let attempt = 0

  for (;;) {
    if (signal?.aborted) return { result: 'timeout', state: latest }
    const delay = attempt < POLL_START_MS.length ? POLL_START_MS[attempt] : POLL_STEADY_MS
    attempt += 1
    await wait(delay)
    if (signal?.aborted) return { result: 'timeout', state: latest }
    if (Date.now() > deadline) return { result: 'timeout', state: latest }

    let body: Awaited<ReturnType<typeof fetchRunSnapshot>>
    try {
      body = await fetchRunSnapshot(traceId)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        // registry 终态窗已过（bus 释放 + 60s 窗超）或从未注册：降级查 DB 终态
        const content = await lookupFinalContent(opts.assistantClientMessageId)
        if (content !== undefined) {
          return { result: 'complete', state: latest, finalContent: content }
        }
        return { result: 'not_found', state: latest }
      }
      // 恢复期瞬时网络抖动/5xx：不放弃，按节奏继续（deadline 兜底）
      continue
    }

    const snap = body.snapshot as Record<string, unknown>
    latest = executionFromSnapshot(snap, traceId)
    const events = Array.isArray(body.events) ? body.events : []
    latest = replayEvents(latest, events as Record<string, unknown>[], lastSeq)
    if (latest && onProgress) onProgress(latest)

    const status = body.status || 'streaming'
    if (status === 'streaming') continue

    const terminal = terminalResult(status)
    if (!terminal) continue
    if (terminal === 'complete') {
      const content = await lookupFinalContent(opts.assistantClientMessageId)
      return { result: 'complete', state: latest, finalContent: content }
    }
    return { result: terminal, state: latest }
  }
}
