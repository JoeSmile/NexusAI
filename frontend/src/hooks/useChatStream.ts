/**
 * Chat 面板流式发送 → 消息列表（Task 30.12 / 47b slice0 + 历史分页）。
 */
import { useCallback, useState } from 'react'

import {
  applyExecutionEvent,
  executionFromSnapshot,
  type ExecutionState,
} from '@/hooks/sseParse'
import { useSSEStream } from '@/hooks/useSSEStream'
import { isRenderDirective, type RenderDirective } from '@/types/render'

export type ChatRole = 'user' | 'assistant' | 'system'

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  status?: 'streaming' | 'done' | 'error' | 'aborted'
  /** Task 63 — agent-driven component mount */
  render?: RenderDirective | null
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

  const abort = useCallback(() => {
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
          onToken: (t) => patch((c) => c + t),
          onPlan: (p) => mergeExecution({ ...p, type: 'plan' }),
          onStep: (p) => mergeExecution({ ...p, type: 'step' }),
          onRetry: () => undefined,
          onReplan: (p) => mergeExecution({ ...p, type: 'replan' }),
          onAbort: () => {
            patch((c) => c, 'aborted')
            setStreaming(false)
          },
          onRetraction: (reason) => {
            patch((c) => `${c}\n\n[retracted: ${reason}]`, 'done')
          },
          onError: (code, message) => {
            setMessages((msgs) =>
              msgs.map((msg) => {
                if (msg.id !== asstId) return msg
                // 已有流式正文 = LLM 已通；事后槽位/写记忆错误不当成整单失败
                if (msg.content.trim()) {
                  return { ...msg, status: 'done' }
                }
                return {
                  ...msg,
                  content: `[${code}] ${message}`,
                  status: 'error',
                }
              }),
            )
            setStreaming(false)
          },
          onDone: (meta) => {
            const snap = executionFromSnapshot(
              meta?.execution_snapshot as Record<string, unknown> | undefined,
              meta?.trace_id ? String(meta.trace_id) : undefined,
            )
            if (snap) setExecution(snap)
            const renderRaw = meta?.render
            const render = isRenderDirective(renderRaw) ? renderRaw : null
            setMessages((msgs) =>
              msgs.map((msg) =>
                msg.id === asstId
                  ? {
                      ...msg,
                      content: msg.content,
                      status: 'done',
                      ...(render ? { render } : {}),
                    }
                  : msg,
              ),
            )
            setStreaming(false)
          },
        },
      )
      setStreaming(false)
    },
    [endpoint, start, streaming, abortFetch],
  )

  const reset = useCallback(() => {
    abort()
    setMessages([])
    setStreaming(false)
    setHasMore(false)
    setExecution(null)
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

  return {
    messages,
    streaming,
    hasMore,
    execution,
    send,
    abort,
    reset,
    appendLocal,
    patchLocal,
    loadHistory,
    replaceHistory,
    prependHistory,
  }
}
