/** 后端响应类型占位（Task 30.10）；后续面板/API 模块逐步收紧。 */

export type RoleName = 'user' | 'tenant_admin' | 'auditor' | 'super_admin'

export interface ApiErrorBody {
  code?: string
  message?: string
  detail?: string | Record<string, unknown>
}

export interface CapabilityItem {
  id: string
  name: string
  kind: string
  provider: string
  status: string
  permission: string
  tenant_id: string
  cost_model?: Record<string, unknown>
  spec?: Record<string, unknown>
}

export interface CapabilityListResponse {
  items: CapabilityItem[]
  total: number
}

export interface InvokeJsonResponse {
  response: string
  capability_id: string
  kind?: string
  cost_source?: string
  upstream?: string | null
  finish_reason?: string
}

export interface HealthResponse {
  status?: string
  [key: string]: unknown
}
