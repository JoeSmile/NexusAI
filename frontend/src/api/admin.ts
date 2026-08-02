import { ApiError, apiFetch, apiGet, apiPost } from '@/api/http'

export type ApiKeyRow = {
  id: number
  key_prefix: string
  role: string
  tenant_id: string
  user_id: string
  is_active: boolean
  description: string
  created_at: string
}

export type CreateKeyResult = {
  api_key: string
  key: ApiKeyRow
}

export type PendingRequest = {
  id: number
  tenant_id: string
  user_id: string
  resource: string
  resource_type: string
  action: string
  status: string
  created_at: string
  params?: Record<string, unknown>
}

export type LlmKeyRow = {
  id?: number
  key_alias?: string
  provider?: string
  [k: string]: unknown
}

export async function listApiKeys() {
  return apiGet<ApiKeyRow[]>('/api/admin/api-keys')
}

export async function createApiKey(body: {
  user_id: string
  role?: string
  tenant_id?: string
  description?: string
}) {
  return apiPost<CreateKeyResult>('/api/admin/api-keys', body)
}

export async function deactivateApiKey(id: number) {
  const res = await apiFetch(`/api/admin/api-keys/${id}`, { method: 'DELETE' })
  if (!res.ok) {
    let body: unknown
    try {
      body = await res.json()
    } catch {
      body = undefined
    }
    throw new ApiError({
      status: res.status,
      code: 'SYS_001',
      message: `delete_failed:${res.status}`,
      body,
    })
  }
  return res.json() as Promise<{ status: string; id: number }>
}

export async function listPendingRequests() {
  return apiGet<PendingRequest[]>('/api/admin/pending-requests')
}

export async function approveRequest(body: {
  request_id: number
  approved: boolean
  reason?: string
}) {
  return apiPost<{ status?: string }>('/api/admin/approve', body)
}

export async function listLlmKeys() {
  return apiGet<LlmKeyRow[]>('/api/admin/llm-keys')
}
