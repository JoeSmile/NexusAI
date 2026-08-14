import { apiGet, apiPost } from '@/api/http'

export type NotificationItem = {
  id: string
  tenant_id: string
  user_id: string
  type: string
  channel: string
  payload: {
    run_id?: string
    node_id?: string
    request_id?: string
    grant_id?: string
    reason?: string
    [k: string]: unknown
  }
  read_at?: string | null
  created_at?: string | null
}

export function listNotificationInbox(params?: { limit?: number; offset?: number }) {
  const q = new URLSearchParams()
  if (params?.limit != null) q.set('limit', String(params.limit))
  if (params?.offset != null) q.set('offset', String(params.offset))
  const qs = q.toString()
  return apiGet<{ items: NotificationItem[] }>(
    `/api/notifications/inbox${qs ? `?${qs}` : ''}`,
  )
}

export function getNotificationUnreadCount() {
  return apiGet<{ unread: number }>('/api/notifications/unread-count')
}

export function markNotificationRead(id: string) {
  return apiPost<{ ok: boolean; id: string }>(`/api/notifications/${id}/read`, {})
}
