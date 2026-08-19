import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

export interface ChatPrefsState {
  modelId: string
  temperature: number
  contextOpen: boolean
  setModelId: (id: string) => void
  setTemperature: (n: number) => void
  setContextOpen: (open: boolean) => void
}

export const useChatPrefsStore = create<ChatPrefsState>()(
  persist(
    (set) => ({
      modelId: '',
      temperature: 0.3,
      contextOpen: false,
      setModelId: (modelId) => set({ modelId }),
      setTemperature: (temperature) => set({ temperature }),
      setContextOpen: (contextOpen) => set({ contextOpen }),
    }),
    {
      // bump key whenever stale sessionStorage reopens the context panel
      name: 'cg-chat-prefs-v5',
      storage: createJSONStorage(() => sessionStorage),
      partialize: (s) => ({
        modelId: s.modelId,
        temperature: s.temperature,
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
