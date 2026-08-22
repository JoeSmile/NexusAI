import type { ComponentType } from 'react'

import type { RenderActionHandler } from '@/types/render'

export type RegisteredRenderProps = {
  payload: Record<string, unknown>
  onAction?: RenderActionHandler
}

/** Whitelist only — arbitrary component strings are rejected by RenderHost. */
export const COMPONENT_REGISTRY: Record<
  string,
  () => Promise<{ default: ComponentType<RegisteredRenderProps> }>
> = {
  hotspot_table: () => import('./HotspotTable'),
}

export const ALLOWED_COMPONENTS = Object.freeze(Object.keys(COMPONENT_REGISTRY))
