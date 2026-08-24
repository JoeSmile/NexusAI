/**
 * Chat 面板流式发送 → 消息列表（Task 30.12 / 47b slice0 + 历史分页）。
 */
import { useCallback, useRef, useState } from 'react'

import { cancelChatStream } from '@/api/chat'
import {
  applyExecutionEvent,
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
}

/** I1: stable UUID for feedback hydrate across refresh. */
export function newClientMessageId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export function useChatStream(endpoint = '/chat/streaming') {
  const { start, abort: abortFetch } = useSSEStream()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [execution, setExecution] = useState<ExecutionState | null>(null)
  const [streamAlert, setStreamAlert] = useState<StreamAlert | null>(null)
  const activeTraceRef = useRef<string | null>(null)
  const reconnectAbortRef = useRef<AbortController | null>(null)

  const abort = useCallback(() => {
    const tid = activeTraceRef.current
    if (tid) void cancelChatStream(tid).catch(() => undefined)
    reconnectAbortRef.current?.abort()
    reconnectAbortRef.current = null
    abortFetch()
    setStreaming(false)
  }, [abortFetch])

  /** Initial page: always replace (empty list or re-entry). */
  const replaceHistory = useCallback((items: ChatMessage[], more: boolean) => {
    setMessages(items)
    setHasMore(more)
  }, [])

  /** Older page: prepend, dedupe by message id. */
  const prependHistory = useCallback((items: ChatMessage[], more: boolean) => {
    setMessages((prev) => {
      const seen = new Set(prev.map((m) => m.id))
      const older = items.filter((m) => !seen.has(m.id))
      return older.length ? [...older, ...prev] : prev
    })
    setHasMore(more)
  }, [])

  /** @deprecated prefer replaceHistory — kept for callers that only fill empty */
  const loadHistory = useCallback((items: ChatMessage[]) => {
    setMessages((prev) => (prev.length > 0 ? prev : items))
  }, [])

  const send = useCallback(
    async (text: string, extra?: Record<string, unknown>) => {
      const trimmed = text.trim()
      if (!trimmed) return
      if (streaming) {
        abortFetch()
        setStreaming(false)
      }

      const userId = newClientMessageId()
      const asstId = newClientMessageId()
      const userMsg: ChatMessage = { id: userId, role: 'user', content: trimmed }
      setMessages((m) => [
        ...m,
        userMsg,
        { id: asstId, role: 'assistant', content: '', status: 'streaming' },
      ])
      setExecution(null)
      setStreamAlert(null)
      activeTraceRef.current = null
      setStreaming(true)

      const mergeExecution = (event: Record<string, unknown>) => {
        setExecution((prev) => applyExecutionEvent(prev, event))
      }

      const patch = (fn: (c: string) => string, status?: ChatMessage['status']) => {
        setMessages((msgs) =>
          msgs.map((msg) =>
            msg.id === asstId
              ? { ...msg, content: fn(msg.content), ...(status ? { status } : {}) }
              : msg,
          ),
        )
      }

      const finishAssistant = (status: ChatMessage['status'] = 'done') => {
        setMessages((msgs) =>
          msgs.map((msg) => (msg.id === asstId ? { ...msg, status } : msg)),
        )
        setStreaming(false)
        activeTraceRef.current = null
      }

      const applyClarification = (payload: Record<string, unknown>) => {
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
        setMessages((msgs) =>
          msgs.map((msg) =>
            msg.id === asstId
              ? {
                  ...msg,
                  content: question || msg.content,
                  clarification: info,
                  status: 'done',
                }
              : msg,
          ),
        )
      }

      await start(
        endpoint,
        {
          method: 'POST',
          body: JSON.stringify({
            message: trimmed,
            user_client_message_id: userId,
            assistant_client_message_id: asstId,
            ...extra,
          }),
        },
        {
          onTraceId: (tid) => {
            activeTraceRef.current = tid
          },
          onToken: (t) => patch((c) => c + t),
          onPlan: (p) => mergeExecution({ ...p, type: 'plan' }),
          onStep: (p) => mergeExecution({ ...p, type: 'step' }),
          onToolCall: (p) => mergeExecution({ ...p, type: 'tool_call' }),
          onToolResult: (p) => mergeExecution({ ...p, type: 'tool_result' }),
          onRetry: () => undefined,
          onReplan: (p) => mergeExecution({ ...p, type: 'replan' }),
          onClarify: (p) => applyClarification(p),
          onStreamAlert: (alert) => setStreamAlert(alert),
          onAbort: () => {
            finishAssistant('aborted')
          },
          onCancelled: () => {
            finishAssistant('aborted')
          },
          onRetraction: () => {
            finishAssistant('done')
          },
          onError: (code, message) => {
            setMessages((msgs) =>
              msgs.map((msg) => {
                if (msg.id !== asstId) return msg
                if (msg.content.trim()) return { ...msg, status: 'done' }
                return {
                  ...msg,
                  content: message ? `（${message}）` : '',
                  status: 'error',
                }
              }),
            )
            setStreamAlert((prev) =>
              prev ?? {
                kind: 'error',
                title: '请求失败',
                message,
                code,
              },
            )
            finishAssistant('error')
          },
          onNetworkError: () => {
            const tid = activeTraceRef.current
            if (!tid) {
              setStreamAlert({
                kind: 'error',
                title: '网络错误',
                message: '连接中断，且无法识别 trace，请重试。',
                code: 'NET_DISCONNECT',
              })
              finishAssistant('error')
              return
            }
            setStreamAlert({
              kind: 'reconnect',
              title: '连接中断',
              message: '正在通过快照恢复执行进度…',
              code: 'NET_RECONNECT',
            })
            reconnectAbortRef.current?.abort()
            const ac = new AbortController()
            reconnectAbortRef.current = ac
            void pollRunSnapshot({
              traceId: tid,
              onProgress: setExecution,
              signal: ac.signal,
            }).then(({ result }) => {
              if (ac.signal.aborted) return
              reconnectAbortRef.current = null
              if (result === 'complete') {
                setStreamAlert({
                  kind: 'info',
                  title: '进度已恢复',
                  message: '编排步骤已从快照对齐；文本流可能不完整。',
                })
                finishAssistant('done')
              } else if (result === 'cancelled') {
                setStreamAlert({
                  kind: 'cancelled',
                  title: '已取消',
                  message: '本次任务在恢复前已被取消。',
                  code: 'CHAT_CANCELLED',
                })
                finishAssistant('aborted')
              } else if (result === 'not_found') {
                finishAssistant('done')
              } else {
                setStreamAlert({
                  kind: 'error',
                  title: '恢复超时',
                  message: '无法从快照恢复完整进度，请查看执行面板或重试。',
                  code: 'RECONNECT_TIMEOUT',
                })
                finishAssistant('error')
              }
            })
          },
          onDone: (meta) => {
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
            setMessages((msgs) =>
              msgs.map((msg) =>
                msg.id === asstId
                  ? {
                      ...msg,
                      content: msg.content,
                      status: 'done',
                      ...(render ? { render } : {}),
                      ...(clarification ? { clarification } : {}),
                    }
                  : msg,
              ),
            )
            finishAssistant('done')
          },
        },
      )
    },
    [endpoint, start, streaming, abortFetch],
  )

  const reset = useCallback(() => {
    abort()
    setMessages([])
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
      setMessages((m) => [...m, { id, role, content, status, imagePreview }])
      return id
    },
    [],
  )

  const patchLocal = useCallback((id: string, content: string, status?: ChatMessage['status']) => {
    setMessages((msgs) =>
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
