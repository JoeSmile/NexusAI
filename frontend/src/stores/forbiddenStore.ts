import { create } from 'zustand'

/** 最近一次 403，供面板红字高亮（30.14 / 30.15）。 */
export interface ForbiddenState {
  code: string
  needed?: string
  message: string
  path?: string
  at: number
}

interface Store {
  last: ForbiddenState | null
  setForbidden: (f: ForbiddenState) => void
  clear: () => void
}

export const useForbiddenStore = create<Store>((set) => ({
  last: null,
  setForbidden: (f) => set({ last: f }),
  clear: () => set({ last: null }),
}))
