/** Sidebar → HomeChat in-place workflow trigger (45b slice 3). */
import { create } from 'zustand'

export type WorkflowTriggerKind = 'hotspot' | 'script'

type TriggerState = {
  kind: WorkflowTriggerKind | null
  nonce: number
  request: (kind: WorkflowTriggerKind) => void
  clear: () => void
}

export const useWorkflowTriggerStore = create<TriggerState>((set) => ({
  kind: null,
  nonce: 0,
  request: (kind) => set({ kind, nonce: Date.now() }),
  clear: () => set({ kind: null }),
}))
