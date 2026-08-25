import { useEffect } from 'react'

import { listAvailableModels } from '@/api/llm'
import { pickDefaultModelId } from '@/lib/chatModels'
import { useChatPrefsStore } from '@/stores/chatPrefsStore'

/** Keep chat model selection aligned with tenant LLM credentials. */
export function useSyncChatModels(enabled = true) {
  const setModelId = useChatPrefsStore((s) => s.setModelId)

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    void (async () => {
      try {
        const res = await listAvailableModels()
        if (cancelled) return
        const next = pickDefaultModelId(
          res.items ?? [],
          useChatPrefsStore.getState().modelId,
        )
        if (next) setModelId(next)
      } catch {
        /* ignore — ContextPanel shows reminder */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [enabled, setModelId])
}
