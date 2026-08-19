import { useCallback, useState } from 'react'
import { toast } from 'sonner'

import {
  cleanBotResponseForFeedback,
  deleteMyFeedback,
  listMyFeedback,
  submitFeedback,
  type FeedbackType,
} from '@/api/feedback'
import { formatApiError } from '@/api/http'
import { WORKSPACE_CHAT_SESSION } from '@/api/chat'

export type BubbleFeedbackState = {
  reaction?: { id: number; type: 'helpful' | 'irrelevant' }
  bookmark?: { id: number }
}

type MapState = Record<string, BubbleFeedbackState>

export function useBubbleFeedback() {
  const [byMsg, setByMsg] = useState<MapState>({})
  const [busy, setBusy] = useState<string | null>(null)

  const hydrate = useCallback(async (sessionId = WORKSPACE_CHAT_SESSION) => {
    try {
      const res = await listMyFeedback({ session_id: sessionId, limit: 50 })
      const next: MapState = {}
      for (const it of res.items) {
        const cid = it.client_message_id
        if (!cid) continue
        const slot = next[cid] ?? {}
        if (it.feedback_type === 'helpful' || it.feedback_type === 'irrelevant') {
          slot.reaction = {
            id: it.id,
            type: it.feedback_type,
          }
        } else if (it.feedback_type === 'bookmark') {
          slot.bookmark = { id: it.id }
        }
        next[cid] = slot
      }
      setByMsg(next)
    } catch (e) {
      // hydrate failure is soft — bubble still usable
      console.warn('feedback hydrate failed', e)
    }
  }, [])

  const copyText = useCallback(async (raw: string) => {
    const text = cleanBotResponseForFeedback(raw)
    try {
      await navigator.clipboard.writeText(text)
      toast.success('已复制')
    } catch (e) {
      toast.error(formatApiError(e, 'clipboard'))
    }
  }, [])

  const toggleReaction = useCallback(
    async (
      clientMessageId: string,
      type: 'helpful' | 'irrelevant',
      botRaw: string,
      userMessage?: string,
    ) => {
      const key = `${clientMessageId}:reaction`
      if (busy) return
      setBusy(key)
      const cur = byMsg[clientMessageId]?.reaction
      try {
        if (cur?.type === type) {
          await deleteMyFeedback(cur.id)
          setByMsg((m) => {
            const slot = { ...(m[clientMessageId] ?? {}) }
            delete slot.reaction
            return { ...m, [clientMessageId]: slot }
          })
          return
        }
        const res = await submitFeedback({
          session_id: WORKSPACE_CHAT_SESSION,
          client_message_id: clientMessageId,
          feedback_type: type,
          rating: type === 'helpful' ? 5 : 1,
          user_message: userMessage || '',
          bot_response: '', // P2: reaction snapshot optional
        })
        setByMsg((m) => ({
          ...m,
          [clientMessageId]: {
            ...(m[clientMessageId] ?? {}),
            reaction: { id: res.feedback_id, type },
          },
        }))
      } catch (e) {
        toast.error(formatApiError(e))
      } finally {
        setBusy(null)
      }
    },
    [busy, byMsg],
  )

  const toggleBookmark = useCallback(
    async (clientMessageId: string, botRaw: string, userMessage?: string) => {
      const key = `${clientMessageId}:bookmark`
      if (busy) return
      setBusy(key)
      const cur = byMsg[clientMessageId]?.bookmark
      try {
        if (cur) {
          await deleteMyFeedback(cur.id)
          setByMsg((m) => {
            const slot = { ...(m[clientMessageId] ?? {}) }
            delete slot.bookmark
            return { ...m, [clientMessageId]: slot }
          })
          return
        }
        const cleaned = cleanBotResponseForFeedback(botRaw)
        if (!cleaned) {
          toast.error('无内容可收藏')
          return
        }
        const res = await submitFeedback({
          session_id: WORKSPACE_CHAT_SESSION,
          client_message_id: clientMessageId,
          feedback_type: 'bookmark',
          user_message: userMessage || '',
          bot_response: cleaned,
        })
        setByMsg((m) => ({
          ...m,
          [clientMessageId]: {
            ...(m[clientMessageId] ?? {}),
            bookmark: { id: res.feedback_id },
          },
        }))
        toast.success('已收藏')
      } catch (e) {
        toast.error(formatApiError(e))
      } finally {
        setBusy(null)
      }
    },
    [busy, byMsg],
  )

  return { byMsg, hydrate, copyText, toggleReaction, toggleBookmark, busy }
}

export type { FeedbackType }
