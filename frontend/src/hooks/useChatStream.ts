/**
 * Chat 面板流式发送 → 消息列表（Task 30.12）。
 */
import { useCallback, useState } from 'react'

import { useSSEStream } from '@/hooks/useSSEStream'

export type ChatRole = 'user' | 'assistant' | 'system'

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  status?: 'streaming' | 'done' | 'error' | 'aborted'
}

function mid(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export function useChatStream(endpoint = '/chat/streaming') {
  const { start, abort } = useSSEStream()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)

  const send = useCallback(
    async (text: string, extra?: Record<string, unknown>) => {
      const trimmed = text.trim()
      if (!trimmed || streaming) return

      const userMsg: ChatMessage = { id: mid(), role: 'user', content: trimmed }
      const asstId = mid()
      setMessages((m) => [
        ...m,
        userMsg,
        { id: asstId, role: 'assistant', content: '', status: 'streaming' },
      ])
      setStreaming(true)

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
          body: JSON.stringify({ message: trimmed, ...extra }),
        },
        {
          onToken: (t) => patch((c) => c + t),
          onAbort: () => {
            patch((c) => c, 'aborted')
            setStreaming(false)
          },
          onRetraction: (reason) => {
            patch((c) => `${c}\n\n[retracted: ${reason}]`, 'done')
          },
          onError: (code, message) => {
            patch((c) => c || `[${code}] ${message}`, 'error')
            setStreaming(false)
          },
          onDone: () => {
            patch((c) => c, 'done')
            setStreaming(false)
          },
        },
      )
      setStreaming(false)
    },
    [endpoint, start, streaming],
  )

  const reset = useCallback(() => {
    abort()
    setMessages([])
    setStreaming(false)
  }, [abort])

  return { messages, streaming, send, abort, reset }
}
