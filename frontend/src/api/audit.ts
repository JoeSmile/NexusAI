import { apiFetch, apiGet } from '@/api/http'

export type AuditLogRow = {
  id: number
  tenant_id: string
  user_id: string
  action: string
  trace_id?: string | null
  model?: string | null
  input_tokens?: number | null
  output_tokens?: number | null
  cost?: number | null
  latency_ms?: number | null
  error_code?: string | null
  ip_address?: string | null
  created_at?: string | null
}

export type AuditQuery = {
  tenant_id?: string
  start?: string
  end?: string
  action?: string
  limit?: number
  offset?: number
}

function toQs(q: AuditQuery): string {
  const p = new URLSearchParams()
  if (q.tenant_id) p.set('tenant_id', q.tenant_id)
  if (q.start) p.set('start', q.start)
  if (q.end) p.set('end', q.end)
  if (q.action) p.set('action', q.action)
  if (q.limit != null) p.set('limit', String(q.limit))
  if (q.offset != null) p.set('offset', String(q.offset))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export async function fetchAuditLogs(q: AuditQuery = {}) {
  return apiGet<AuditLogRow[]>(`/api/audit/logs${toQs(q)}`)
}

/** 下载 CSV（blob）；成功时触发浏览器保存。 */
export async function exportAuditCsv(q: Omit<AuditQuery, 'limit' | 'offset'> = {}) {
  const res = await apiFetch(`/api/audit/export${toQs(q)}`)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `export_failed:${res.status}`)
  }
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') || ''
  const m = /filename=([^;]+)/i.exec(cd)
  const filename = (m?.[1] || 'audit_export.csv').replace(/"/g, '')
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
