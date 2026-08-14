import { apiGet, apiPost } from '@/api/http'

export type ApprovalRequest = {
  id: string
  tenant_id: string
  run_id: string
  node_id: string
  applicant_user_id: string
  needed_perm: string
  org_unit_id: string
  capability_id: string
  status: string
  requestable_mode?: string
  approval_note?: string | null
  escalated_at?: string | null
  reviewed_by?: string | null
  reviewed_at?: string | null
  review_reason?: string | null
  workflow_name?: string | null
  created_at?: string | null
}

export function listApprovalInbox() {
  return apiGet<{ items: ApprovalRequest[] }>('/api/workflow-approvals/inbox')
}

export function approveRequest(
  id: string,
  body?: { reason?: string; scope?: 'single' | 'recurring'; ttl_days?: number },
) {
  return apiPost<{
    ok: boolean
    request_id: string
    grant_id: string
    run_id: string
    status: string
  }>(`/api/workflow-approvals/${id}/approve`, body ?? {})
}

export function rejectRequest(id: string, body?: { reason?: string }) {
  return apiPost<{ ok: boolean; request_id: string; status: string }>(
    `/api/workflow-approvals/${id}/reject`,
    body ?? {},
  )
}
