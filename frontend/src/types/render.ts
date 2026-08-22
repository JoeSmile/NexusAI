/** Task 63 — agent-driven component render protocol. */

export type HotspotTableItem = {
  title?: string
  summary?: string
  category?: string
  score?: number
  similar_to_previous?: boolean
}

export type RenderDirective = {
  component: string
  payload: Record<string, unknown>
}

export type RenderAction =
  | {
      action: 'script.gen'
      hotspots: HotspotTableItem[]
      trace_id?: string
    }
  | {
      action: string
      payload?: Record<string, unknown>
    }

export type RenderActionHandler = (action: RenderAction) => void | Promise<void>

export function isRenderDirective(value: unknown): value is RenderDirective {
  if (!value || typeof value !== 'object') return false
  const v = value as Record<string, unknown>
  return typeof v.component === 'string' && typeof v.payload === 'object' && v.payload !== null
}
