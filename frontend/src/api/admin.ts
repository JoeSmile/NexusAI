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

export type LlmKeyPurpose = 'chat' | 'embedding'

export type LlmKeyRow = {
  id: number
  key_alias: string
  provider: string
  purpose?: LlmKeyPurpose | string
  tenant_id: string
  base_url?: string
  model?: string | null
  allowed_models?: string[]
  /** 服务端脱敏：前后各 8 位 + ***，无明文 */
  key_preview?: string
  owner_user_id?: string | null
  is_active: boolean
  created_at?: string
  embedding_dimensions?: number | null
}

export type CreateLlmKeyBody = {
  key_alias: string
  provider: LlmKeyPurpose
  api_key_plaintext: string
  model: string
  base_url: string
  description?: string
  tenant_id?: string
}

export type PatchLlmKeyBody = {
  key_alias?: string
  model?: string
  base_url?: string
  api_key_plaintext?: string
  is_active?: boolean
}

export async function listApiKeys() {
  return apiGet<ApiKeyRow[]>('/api/admin/api-keys', { quietForbidden: true })
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

export async function createLlmKey(body: CreateLlmKeyBody) {
  return apiPost<{ id: number; key_alias: string; provider: string }>(
    '/api/admin/llm-keys',
    body,
  )
}

export async function patchLlmKey(id: number, body: PatchLlmKeyBody) {
  const res = await apiFetch(`/api/admin/llm-keys/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let errBody: unknown
    try {
      errBody = await res.json()
    } catch {
      errBody = undefined
    }
    throw new ApiError({
      status: res.status,
      code: 'SYS_001',
      message: `patch_failed:${res.status}`,
      body: errBody,
    })
  }
  return res.json() as Promise<{ status: string; id: number }>
}

export async function deactivateLlmKey(id: number) {
  const res = await apiFetch(`/api/admin/llm-keys/${id}`, { method: 'DELETE' })
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
