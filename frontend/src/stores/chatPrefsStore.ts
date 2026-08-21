import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

export interface ChatPrefsState {
  modelId: string
  temperature: number
  maxTokens: number
  contextOpen: boolean
  setModelId: (id: string) => void
  setTemperature: (n: number) => void
  setMaxTokens: (n: number) => void
  setContextOpen: (open: boolean) => void
}

export const useChatPrefsStore = create<ChatPrefsState>()(
  persist(
    (set) => ({
      modelId: '',
      temperature: 0.3,
      maxTokens: 0,
      contextOpen: false,
      setModelId: (modelId) => set({ modelId }),
      setTemperature: (temperature) => set({ temperature }),
      setMaxTokens: (maxTokens) => set({ maxTokens }),
      setContextOpen: (contextOpen) => set({ contextOpen }),
    }),
    {
      // bump key whenever stale sessionStorage reopens the context panel
      name: 'cg-chat-prefs-v6',
      storage: createJSONStorage(() => sessionStorage),
      partialize: (s) => ({
        modelId: s.modelId,
        temperature: s.temperature,
        maxTokens: s.maxTokens,
        // contextOpen intentionally NOT persisted — always start closed
      }),
      merge: (persisted, current) => {
        const p = (persisted ?? {}) as Partial<ChatPrefsState>
        return {
          ...current,
          ...p,
          contextOpen: false,
        }
      },
    },
  ),
)
