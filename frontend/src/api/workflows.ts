import { apiDelete, apiGet, apiPatch, apiPost } from '@/api/http'

export type WorkflowNode = {
  node_id: string
  capability_id: string
  kind?: 'capability'
  params?: Record<string, unknown>
  /** Wave E: 'true' | 'sensitive' | 'false' (bool still accepted by API) */
  requestable?: boolean | 'true' | 'sensitive' | 'false'
  approval_note?: string | null
}

export type WorkflowParamSpec = {
  name?: string
  type?: 'string' | 'number' | 'boolean' | 'enum'
  required?: boolean
  description?: string
  default?: unknown
  enum_values?: string[] | null
}

export type WorkflowIR = {
  ir_schema?: string
  nodes: WorkflowNode[]
  edges?: unknown[]
  inputs?: Record<string, WorkflowParamSpec>
  output_node_id?: string | null
}

export function workflowRunInputs(ir?: WorkflowIR | null): Record<string, WorkflowParamSpec> {
  const raw = ir?.inputs
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {}
  return raw
}

export type RequestPolicy = {
  scope?: 'single' | 'recurring'
  default_ttl_days?: number
  auto_renew?: boolean
}

export type Workflow = {
  id: string
  tenant_id: string
  org_unit_id: string | null
  name: string
  status: 'draft' | 'published' | 'archived' | string
  ir: WorkflowIR
  version: string
  revision: number
  forked_from_id: string | null
  created_by: string
  request_policy?: RequestPolicy
  created_at: string | null
  updated_at: string | null
}

export type WorkflowListResponse = {
  items: Workflow[]
  limit: number
  offset: number
}

export function listWorkflows(opts?: { status?: string; limit?: number; offset?: number }) {
  const p = new URLSearchParams()
  if (opts?.status) p.set('status', opts.status)
  if (opts?.limit != null) p.set('limit', String(opts.limit))
  if (opts?.offset != null) p.set('offset', String(opts.offset))
  const qs = p.toString()
  return apiGet<WorkflowListResponse>(`/api/workflows${qs ? `?${qs}` : ''}`)
}

export function getWorkflow(id: string) {
  return apiGet<Workflow>(`/api/workflows/${id}`)
}

export function createWorkflow(body: { name: string; ir?: WorkflowIR; org_unit_id?: string | null }) {
  return apiPost<Workflow>('/api/workflows', body)
}

export function patchWorkflow(
  id: string,
  body: {
    base_revision: number
    name?: string
    ir?: WorkflowIR
    org_unit_id?: string | null
    request_policy?: RequestPolicy
  },
) {
  return apiPatch<Workflow>(`/api/workflows/${id}`, body)
}

export function publishWorkflow(id: string, base_revision?: number) {
  return apiPost<Workflow>(`/api/workflows/${id}/publish`, {
    base_revision: base_revision ?? null,
  })
}

export function forkDraft(id: string) {
  return apiPost<Workflow>(`/api/workflows/${id}/fork-draft`, {})
}

export function deleteWorkflow(id: string) {
  return apiDelete<{ ok: boolean; id: string }>(`/api/workflows/${id}`)
}
