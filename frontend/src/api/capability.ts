import { apiGet } from '@/api/http'

export type CapabilityItem = {
  id: string
  name: string
  kind: string
  provider: string
  status: string
  permission?: string
  tenant_id?: string
  cost_model?: Record<string, unknown>
  spec?: Record<string, unknown>
}

export type CapabilityListResponse = {
  items: CapabilityItem[]
  total: number
}

export async function listCapabilities(opts?: {
  kind?: string
  provider?: string
  include_disabled?: boolean
}) {
  const p = new URLSearchParams()
  if (opts?.kind) p.set('kind', opts.kind)
  if (opts?.provider) p.set('provider', opts.provider)
  if (opts?.include_disabled) p.set('include_disabled', 'true')
  const qs = p.toString()
  return apiGet<CapabilityListResponse>(`/api/capabilities${qs ? `?${qs}` : ''}`)
}
