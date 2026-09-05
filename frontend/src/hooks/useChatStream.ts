/**
 * Chat 面板流式发送 → 消息列表（Task 30.12 / 47b slice0 + 历史分页）。
 * Task 85: 流式气泡独立 state + 代际守卫，避免每 token 重写历史数组。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { cancelChatStream } from '@/api/chat'
import {
  applyExecutionEvent,
  classifyStreamError,
  executionFromSnapshot,
  type ExecutionState,
  type StreamAlert,
} from '@/hooks/sseParse'
import { pollRunSnapshot } from '@/hooks/streamReconnect'
import { useSSEStream } from '@/hooks/useSSEStream'
import { isRenderDirective, type RenderDirective } from '@/types/render'

export type ChatRole = 'user' | 'assistant' | 'system'

export type ClarificationInfo = {
  source: string
  question: string
  options: string[]
  trace_id?: string
  original_query?: string
}

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  status?: 'streaming' | 'done' | 'error' | 'aborted'
  /** Task 63 — agent-driven component mount */
  render?: RenderDirective | null
  /** Task 65 — pending clarification card */
  clarification?: ClarificationInfo | null
  /** Local preview URL for attached images */
  imagePreview?: string
  /** DB chat_messages.id — history rows only; used as pagination cursor */
  dbId?: number
  /** Task 80.2 — exact|template cache hit on this assistant turn */
  cacheHit?: boolean
  cacheType?: 'exact' | 'template'
}

/** I1: stable UUID for feedback hydrate across refresh. */
export function newClientMessageId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function cacheFromDone(meta?: Record<string, unknown>): {
  cacheHit?: boolean
  cacheType?: ChatMessage['cacheType']
} {
  const raw = String(meta?.cache_type || '')
  if (raw !== 'template' && raw !== 'exact') return {}
  const hit =
    meta?.cache_hit === true || String(meta?.finish_reason || '') === 'cache_hit'
  if (!hit) return {}
  return { cacheHit: true, cacheType: raw }
}

export function useChatStream(endpoint = '/chat/streaming') {
  const { start, abort: abortFetch } = useSSEStream()
  const [committed, setCommitted] = useState<ChatMessage[]>([])
  const [streamingMsg, setStreamingMsg] = useState<ChatMessage | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [execution, setExecution] = useState<ExecutionState | null>(null)
  const [streamAlert, setStreamAlert] = useState<StreamAlert | null>(null)
  const activeTraceRef = useRef<string | null>(null)
  const reconnectAbortRef = useRef<AbortController | null>(null)
  const generationRef = useRef(0)
  const streamingMsgRef = useRef<ChatMessage | null>(null)
  const abortRef = useRef<() => void>(() => undefined)

  const messages = useMemo(
    () => (streamingMsg ? [...committed, streamingMsg] : committed),
    [committed, streamingMsg],
  )

  const abort = useCallback(() => {
    generationRef.current += 1
    const tid = activeTraceRef.current
    if (tid) void cancelChatStream(tid).catch(() => undefined)
    reconnectAbortRef.current?.abort()
    reconnectAbortRef.current = null
    abortFetch()
    const leftover = streamingMsgRef.current
    if (leftover?.status === 'streaming') {
      streamingMsgRef.current = null
      setStreamingMsg(null)
      setCommitted((m) => [...m, { ...leftover, status: 'aborted' }])
    }
    setStreaming(false)
  }, [abortFetch])

  useEffect(() => {
    abortRef.current = abort
  }, [abort])
  useEffect(() => () => abortRef.current(), [])

  /** Initial page: always replace (empty list or re-entry). */
  const replaceHistory = useCallback((items: ChatMessage[], more: boolean) => {
    setCommitted(items)
    setStreamingMsg(null)
    streamingMsgRef.current = null
    setHasMore(more)
  }, [])

  /** Older page: prepend, dedupe by message id. */
  const prependHistory = useCallback((items: ChatMessage[], more: boolean) => {
    setCommitted((prev) => {
      const seen = new Set(prev.map((m) => m.id))
      const older = items.filter((m) => !seen.has(m.id))
      return older.length ? [...older, ...prev] : prev
    })
    setHasMore(more)
  }, [])

  /** @deprecated prefer replaceHistory — kept for callers that only fill empty */
  const loadHistory = useCallback((items: ChatMessage[]) => {
    setCommitted((prev) => (prev.length > 0 ? prev : items))
  }, [])

  const send = useCallback(
    async (text: string, extra?: Record<string, unknown>) => {
      const trimmed = text.trim()
      if (!trimmed) return
      if (streamingMsgRef.current) {
        abortFetch()
        generationRef.current += 1
        const leftover = streamingMsgRef.current
        streamingMsgRef.current = null
        setStreamingMsg(null)
        setCommitted((m) => [...m, { ...leftover, status: 'aborted' }])
        setStreaming(false)
      }

      const extraIn = extra || {}
      const preview =
        typeof extraIn.imagePreview === 'string' ? extraIn.imagePreview : ''
      const payloadExtra = { ...extraIn }
      delete payloadExtra.imagePreview

      const userId = newClientMessageId()
      const asstId = newClientMessageId()
      const userMsg: ChatMessage = {
        id: userId,
        role: 'user',
        content: trimmed,
        ...(preview ? { imagePreview: preview } : {}),
      }
      const asstMsg: ChatMessage = {
        id: asstId,
        role: 'assistant',
        content: '',
        status: 'streaming',
      }
      const gen = ++generationRef.current
      const alive = () => generationRef.current === gen

      setCommitted((m) => [...m, userMsg])
      streamingMsgRef.current = asstMsg
      setStreamingMsg(asstMsg)
      setExecution(null)
      setStreamAlert(null)
      activeTraceRef.current = null
      setStreaming(true)

      const mergeExecution = (event: Record<string, unknown>) => {
        if (!alive()) return
        setExecution((prev) => applyExecutionEvent(prev, event))
      }

      const patchStream = (fn: (c: string) => string, status?: ChatMessage['status']) => {
        if (!alive()) return
        const prev = streamingMsgRef.current
        if (!prev || prev.id !== asstId) return
        const next = {
          ...prev,
          content: fn(prev.content),
          ...(status ? { status } : {}),
        }
        streamingMsgRef.current = next
        setStreamingMsg(next)
      }

      const commitAssistant = (patch: Partial<ChatMessage>) => {
        if (!alive()) return
        const prev = streamingMsgRef.current
        if (!prev || prev.id !== asstId) return
        const done = { ...prev, ...patch }
        streamingMsgRef.current = null
        setStreamingMsg(null)
        setCommitted((m) => [...m, done])
        setStreaming(false)
        activeTraceRef.current = null
      }

      const applyClarification = (payload: Record<string, unknown>) => {
        if (!alive()) return
        const question = String(payload.question || '')
        const options = Array.isArray(payload.options)
          ? payload.options.map((o) => String(o))
          : []
        const info: ClarificationInfo = {
          source: String(payload.source || ''),
          question,
          options,
          trace_id: payload.trace_id ? String(payload.trace_id) : undefined,
          original_query: payload.original_query
            ? String(payload.original_query)
            : undefined,
        }
        commitAssistant({
          content: question || streamingMsgRef.current?.content || '',
          clarification: info,
          status: 'done',
        })
      }

      await start(
        endpoint,
        {
          method: 'POST',
          body: JSON.stringify({
            message: trimmed,
            user_client_message_id: userId,
            assistant_client_message_id: asstId,
            ...payloadExtra,
          }),
        },
        {
          onTraceId: (tid) => {
            if (!alive()) return
            activeTraceRef.current = tid
          },
          onToken: (t) => patchStream((c) => c + t),
          onPlan: (p) => mergeExecution({ ...p, type: 'plan' }),
          onStep: (p) => mergeExecution({ ...p, type: 'step' }),
          onToolCall: (p) => mergeExecution({ ...p, type: 'tool_call' }),
          onToolResult: (p) => mergeExecution({ ...p, type: 'tool_result' }),
          onRetry: () => undefined,
          onReplan: (p) => mergeExecution({ ...p, type: 'replan' }),
          onClarify: (p) => applyClarification(p),
          onStreamAlert: (alert) => {
            if (!alive()) return
            setStreamAlert(alert)
          },
          onAbort: () => {
            commitAssistant({ status: 'aborted' })
          },
          onCancelled: () => {
            commitAssistant({ status: 'aborted' })
          },
          onRetraction: () => {
            commitAssistant({ status: 'done' })
          },
          onError: (code, message) => {
            if (!alive()) return
            const prev = streamingMsgRef.current
            const has = Boolean(prev?.content.trim())
            commitAssistant(
              has
                ? { status: 'done' }
                : {
                    content: message ? `（${message}）` : '',
                    status: 'error',
                  },
            )
            setStreamAlert((cur) =>
              cur ?? {
                kind: 'error',
                title: '请求失败',
                message,
                code,
                errorClass: classifyStreamError(code),
              },
            )
          },
          onNetworkError: () => {
            if (!alive()) return
            const tid = activeTraceRef.current
            if (!tid) {
              setStreamAlert({
                kind: 'error',
                title: '网络错误',
                message: '连接中断，且无法识别 trace，请重试。',
                code: 'NET_DISCONNECT',
                errorClass: 'network',
              })
              commitAssistant({ status: 'error' })
              return
            }
            setStreamAlert({
              kind: 'reconnect',
              title: '连接中断',
              message: '正在通过快照恢复执行进度…',
              code: 'NET_RECONNECT',
              errorClass: 'network',
            })
            reconnectAbortRef.current?.abort()
            const ac = new AbortController()
            reconnectAbortRef.current = ac
            void pollRunSnapshot({
              traceId: tid,
              onProgress: setExecution,
              signal: ac.signal,
            }).then(({ result }) => {
              if (ac.signal.aborted || !alive()) return
              reconnectAbortRef.current = null
              if (result === 'complete') {
                setStreamAlert({
                  kind: 'info',
                  title: '进度已恢复',
                  message: '编排步骤已从快照对齐；文本流可能不完整。',
                })
                commitAssistant({ status: 'done' })
              } else if (result === 'cancelled') {
                setStreamAlert({
                  kind: 'cancelled',
                  title: '已取消',
                  message: '本次任务在恢复前已被取消。',
                  code: 'CHAT_CANCELLED',
                })
                commitAssistant({ status: 'aborted' })
              } else if (result === 'not_found') {
                commitAssistant({ status: 'done' })
              } else {
                setStreamAlert({
                  kind: 'error',
                  title: '恢复超时',
                  message: '无法从快照恢复完整进度，请查看执行面板或重试。',
                  code: 'RECONNECT_TIMEOUT',
                  errorClass: 'timeout',
                })
                commitAssistant({ status: 'error' })
              }
            })
          },
          onDone: (meta) => {
            if (!alive()) return
            const tid = meta?.trace_id ? String(meta.trace_id) : activeTraceRef.current
            if (tid) activeTraceRef.current = tid
            const snap = executionFromSnapshot(
              meta?.execution_snapshot as Record<string, unknown> | undefined,
              tid || undefined,
            )
            if (snap) setExecution(snap)
            const renderRaw = meta?.render
            const render = isRenderDirective(renderRaw) ? renderRaw : null
            const finishReason = String(meta?.finish_reason || '')
            const clarificationRaw = meta?.clarification
            const clarification =
              finishReason === 'clarification_pending' &&
              clarificationRaw &&
              typeof clarificationRaw === 'object'
                ? (clarificationRaw as ClarificationInfo)
                : null
            const cache = cacheFromDone(meta)
            const isCommand =
              finishReason === 'command_result' ||
              String(meta?.type || '') === 'command_result'
            commitAssistant({
              status: 'done',
              ...(isCommand ? { role: 'system' as const } : {}),
              ...(render ? { render } : {}),
              ...(clarification ? { clarification } : {}),
              ...cache,
            })
          },
        },
      )
    },
    [endpoint, start, abortFetch],
  )

  const reset = useCallback(() => {
    abort()
    setCommitted([])
    setStreamingMsg(null)
    streamingMsgRef.current = null
    setStreaming(false)
    setHasMore(false)
    setExecution(null)
    setStreamAlert(null)
  }, [abort])

  const appendLocal = useCallback(
    (
      role: ChatRole,
      content: string,
      status: ChatMessage['status'] = 'done',
      imagePreview?: string,
    ) => {
      const id = newClientMessageId()
      setCommitted((m) => [...m, { id, role, content, status, imagePreview }])
      return id
    },
    [],
  )

  const patchLocal = useCallback((id: string, content: string, status?: ChatMessage['status']) => {
    setStreamingMsg((prev) => {
      if (prev?.id !== id) return prev
      const next = { ...prev, content, ...(status ? { status } : {}) }
      streamingMsgRef.current = next
      return next
    })
    setCommitted((msgs) =>
      msgs.map((msg) =>
        msg.id === id
          ? { ...msg, content, ...(status ? { status } : {}) }
          : msg,
      ),
    )
  }, [])

  const dismissStreamAlert = useCallback(() => setStreamAlert(null), [])

  return {
    messages,
    streaming,
    hasMore,
    execution,
    streamAlert,
    send,
    abort,
    reset,
    appendLocal,
    patchLocal,
    loadHistory,
    replaceHistory,
    prependHistory,
    dismissStreamAlert,
  }
}
