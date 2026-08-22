/**
 * SSE 事件分发（后端 /chat/streaming 协议）+ eventsource-parser 封装。
 */
import { createParser, type EventSourceMessage } from 'eventsource-parser'

export type ExecutionStepStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'skipped'

export type ActiveToolCall = {
  stepId: string
  capabilityId: string
  label: string
}

export type ExecutionStep = {
  id: string
  capability_id: string
  status: ExecutionStepStatus
  summary?: string
}

export type ExecutionState = {
  goal?: string
  steps: ExecutionStep[]
  traceId?: string
  activeTool?: ActiveToolCall | null
}

export type StreamAlertKind =
  | 'error'
  | 'guardrail'
  | 'retraction'
  | 'reconnect'
  | 'cancelled'
  | 'info'

export type StreamAlert = {
  kind: StreamAlertKind
  title?: string
  message: string
  code?: string
}

export type SSEHandlers = {
  onToken?: (text: string) => void
  onAbort?: (reason: string) => void
  onRetraction?: (reason: string) => void
  onError?: (code: string, message: string) => void
  onDone?: (meta?: Record<string, unknown>) => void
  onPlan?: (payload: Record<string, unknown>) => void
  onStep?: (payload: Record<string, unknown>) => void
  onToolCall?: (payload: Record<string, unknown>) => void
  onToolResult?: (payload: Record<string, unknown>) => void
  onRetry?: (payload: Record<string, unknown>) => void
  onReplan?: (payload: Record<string, unknown>) => void
  onCancelled?: (reason: string) => void
  onTraceId?: (traceId: string) => void
  onStreamAlert?: (alert: StreamAlert) => void
  onNetworkError?: (error: Error) => void
}

function stepStatus(raw: unknown): ExecutionStepStatus {
  const s = String(raw || 'pending')
  if (
    s === 'running' ||
    s === 'succeeded' ||
    s === 'failed' ||
    s === 'skipped' ||
    s === 'pending'
  ) {
    return s
  }
  return 'pending'
}

/** 从 plan/step SSE 或 execution_snapshot 合并状态。 */
export function applyExecutionEvent(
  prev: ExecutionState | null,
  event: Record<string, unknown>,
): ExecutionState {
  const base: ExecutionState = prev
    ? { ...prev, steps: [...prev.steps] }
    : { steps: [] }
  const t = String(event.type || '')
  if (t === 'plan') {
    base.goal = String(event.goal || base.goal || '')
    const steps = Array.isArray(event.steps) ? event.steps : []
    const byId = new Map(base.steps.map((s) => [s.id, s]))
    for (const raw of steps) {
      if (!raw || typeof raw !== 'object') continue
      const row = raw as Record<string, unknown>
      const id = String(row.id || '')
      if (!id) continue
      const existing = byId.get(id)
      byId.set(id, {
        id,
        capability_id: String(row.capability_id || existing?.capability_id || ''),
        status: existing?.status || 'pending',
        summary: existing?.summary,
      })
    }
    base.steps = Array.from(byId.values())
    return base
  }
  if (t === 'step') {
    const id = String(event.id || '')
    if (!id) return base
    const idx = base.steps.findIndex((s) => s.id === id)
    const next: ExecutionStep = {
      id,
      capability_id: String(event.capability_id || base.steps[idx]?.capability_id || ''),
      status: stepStatus(event.status),
      summary: event.summary ? String(event.summary) : base.steps[idx]?.summary,
    }
    if (idx >= 0) base.steps[idx] = next
    else base.steps.push(next)
    if (next.status === 'running') {
      base.activeTool = {
        stepId: id,
        capabilityId: next.capability_id,
        label: next.capability_id || id,
      }
    } else if (base.activeTool?.stepId === id) {
      base.activeTool = null
    }
    return base
  }
  if (t === 'tool_call') {
    const stepId = String(event.step_id || event.id || '')
    const capabilityId = String(event.capability_id || '')
    base.activeTool = {
      stepId,
      capabilityId,
      label: String(event.label || capabilityId || stepId),
    }
    return base
  }
  if (t === 'tool_result') {
    const stepId = String(event.step_id || event.id || '')
    if (base.activeTool?.stepId === stepId) base.activeTool = null
    return base
  }
  return base
}

export function executionFromSnapshot(
  snap: Record<string, unknown> | undefined,
  traceId?: string,
): ExecutionState | null {
  if (!snap || typeof snap !== 'object') return null
  const nodes = Array.isArray(snap.nodes) ? snap.nodes : []
  if (!nodes.length && !snap.goal) return null
  return {
    goal: String(snap.goal || ''),
    traceId,
    steps: nodes.map((n) => {
      const row = n as Record<string, unknown>
      return {
        id: String(row.id || ''),
        capability_id: String(row.capability_id || ''),
        status: stepStatus(row.status),
        summary: row.summary ? String(row.summary) : undefined,
      }
    }),
  }
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
  if (t === 'plan') {
    h.onPlan?.(obj)
    return 'continue'
  }
  if (t === 'step') {
    h.onStep?.(obj)
    return 'continue'
  }
  if (t === 'tool_call') {
    h.onToolCall?.(obj)
    return 'continue'
  }
  if (t === 'tool_result') {
    h.onToolResult?.(obj)
    return 'continue'
  }
  if (t === 'retry') {
    h.onRetry?.(obj)
    return 'continue'
  }
  if (t === 'replan') {
    h.onReplan?.(obj)
    return 'continue'
  }
  if (t === 'abort') {
    h.onAbort?.(String(obj.reason || 'abort'))
    h.onStreamAlert?.({
      kind: 'guardrail',
      title: '内容被护栏拦截',
      message: String(obj.reason || 'abort'),
      code: 'GUARDRAIL_ABORT',
    })
    return 'done'
  }
  if (t === 'retraction') {
    h.onRetraction?.(String(obj.reason || 'retraction'))
    h.onStreamAlert?.({
      kind: 'retraction',
      title: '输出已截断',
      message:
        obj.reason === 'length_exceeded'
          ? '回复过长，已截断保留前 4000 字。'
          : String(obj.reason || 'retraction'),
      code: String(obj.reason || 'retraction'),
    })
    return 'continue'
  }
  if (t === 'error') {
    h.onError?.(String(obj.code || 'SYS_001'), String(obj.message || 'error'))
    h.onStreamAlert?.({
      kind: 'error',
      title: '请求失败',
      message: String(obj.message || 'error'),
      code: String(obj.code || 'SYS_001'),
    })
    return 'done'
  }
  if (t === 'cancelled') {
    h.onCancelled?.(String(obj.reason || 'cancelled'))
    h.onStreamAlert?.({
      kind: 'cancelled',
      title: '已取消',
      message: '本次生成已被取消。',
      code: 'CHAT_CANCELLED',
    })
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
