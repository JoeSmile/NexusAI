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

export type ErrorClass = 'framework' | 'business' | 'rate_limit' | 'timeout' | 'network'

export const STREAM_ERROR = {
  PARSE_FAILED: 'PARSE_FAILED',
  SYS_001: 'SYS_001',
  LLM_002: 'LLM_002',
  RATE_001: 'RATE_001',
  NET_DISCONNECT: 'NET_DISCONNECT',
  NET_RECONNECT: 'NET_RECONNECT',
  RECONNECT_TIMEOUT: 'RECONNECT_TIMEOUT',
  CHAT_CANCELLED: 'CHAT_CANCELLED',
  GUARDRAIL_ABORT: 'GUARDRAIL_ABORT',
} as const

export function classifyStreamError(code: string): ErrorClass {
  const c = String(code || '')
  if (c === STREAM_ERROR.PARSE_FAILED) return 'framework'
  if (c.startsWith('NET_')) return 'network'
  if (c.startsWith('RATE_')) return 'rate_limit'
  if (c.includes('TIMEOUT')) return 'timeout'
  return 'business'
}

export type StreamAlert = {
  kind: StreamAlertKind
  title?: string
  message: string
  code?: string
  errorClass?: ErrorClass
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
  onClarify?: (payload: Record<string, unknown>) => void
  onCommandResult?: (payload: Record<string, unknown>) => void
  onCancelled?: (reason: string) => void
  onTraceId?: (traceId: string) => void
  onStreamAlert?: (alert: StreamAlert) => void
  onNetworkError?: (error: Error) => void
}

const STEP_STATUS_RANK: Record<ExecutionStepStatus, number> = {
  pending: 0,
  running: 1,
  succeeded: 2,
  failed: 2,
  skipped: 2,
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

function mergeStepStatus(
  current: ExecutionStepStatus | undefined,
  incoming: ExecutionStepStatus,
): ExecutionStepStatus {
  if (!current) return incoming
  if (STEP_STATUS_RANK[incoming] < STEP_STATUS_RANK[current]) return current
  return incoming
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
    base.steps = base.steps.filter((s) => s.id !== '_planning')
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
        status: existing?.status || stepStatus(row.status || 'pending'),
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
    const incoming = stepStatus(event.status)
    const status = mergeStepStatus(base.steps[idx]?.status, incoming)
    const next: ExecutionStep = {
      id,
      capability_id: String(event.capability_id || base.steps[idx]?.capability_id || ''),
      status,
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
    console.warn('sse parse failed')
    h.onStreamAlert?.({
      kind: 'info',
      title: '解析失败',
      message: '收到无法解析的流式帧',
      code: STREAM_ERROR.PARSE_FAILED,
      errorClass: 'framework',
    })
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
  if (t === 'task_plan_pending') {
    h.onPlan?.({
      type: 'plan',
      goal: '正在理解你的需求…',
      steps: [
        {
          id: '_planning',
          capability_id: 'task.plan',
          status: 'running',
        },
      ],
    })
    h.onStreamAlert?.({
      kind: 'info',
      title: '正在理解你的需求',
      message: String(obj.message || '正在规划任务步骤…'),
      code: 'TASK_PLAN_PENDING',
    })
    return 'continue'
  }
  if (t === 'task_plan_done') {
    const status = String(obj.status || '')
    if (status === 'timeout') {
      h.onStreamAlert?.({
        kind: 'info',
        title: '规划超时',
        message: '规划超时，已改为直接回答。',
        code: 'TASK_PLAN_TIMEOUT',
      })
    }
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
  if (t === 'clarify') {
    h.onClarify?.(obj)
    return 'continue'
  }
  if (t === 'command_result') {
    h.onCommandResult?.(obj)
    h.onDone?.({ ...obj, finish_reason: 'command_result', path: 'long' })
    return 'done'
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
    const code = String(obj.code || STREAM_ERROR.SYS_001)
    const message = String(obj.message || 'error')
    h.onError?.(code, message)
    h.onStreamAlert?.({
      kind: 'error',
      title: '请求失败',
      message,
      code,
      errorClass: classifyStreamError(code),
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
