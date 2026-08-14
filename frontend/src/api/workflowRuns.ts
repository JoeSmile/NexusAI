import { apiGet, apiPost } from '@/api/http'

export type WorkflowRun = {
  id: string
  tenant_id: string
  workflow_id: string
  workflow_name?: string | null
  workflow_status?: string | null
  org_unit_id: string
  status: string
  workflow_version?: string
  workflow_revision?: number
  acting_user_id?: string
  error_code?: string | null
  error_message?: string | null
  created_at?: string | null
  updated_at?: string | null
  finished_at?: string | null
  hang_summary?: string | null
  waiting_nodes?: Array<{
    node_id: string
    needed_perm: string
    capability_id: string
    waiting_for: string
    escalated_at?: string | null
    approval_note?: string | null
  }>
}

export type EvidenceItem = {
  kind?: string
  title: string
  snippet?: string | null
  uri?: string | null
  source_node_id?: string | null
}

export type RunNode = {
  id: string
  node_id: string
  status: string
  attempt: number
  output?: unknown
  evidence?: EvidenceItem[]
  error_message?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export function startRun(workflowId: string) {
  return apiPost<WorkflowRun>(`/api/workflows/${workflowId}/runs`, {})
}

export function listRuns(opts?: { status?: string; limit?: number; offset?: number }) {
  const p = new URLSearchParams()
  if (opts?.status) p.set('status', opts.status)
  if (opts?.limit != null) p.set('limit', String(opts.limit))
  if (opts?.offset != null) p.set('offset', String(opts.offset))
  const qs = p.toString()
  return apiGet<{ items: WorkflowRun[]; limit: number; offset: number }>(
    `/api/runs${qs ? `?${qs}` : ''}`,
  )
}

export function getRun(runId: string) {
  return apiGet<WorkflowRun>(`/api/runs/${runId}`)
}

export function getRunNodes(runId: string) {
  return apiGet<{ run_id: string; items: RunNode[] }>(`/api/runs/${runId}/nodes`)
}
