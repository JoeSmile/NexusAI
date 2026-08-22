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
  trace_id?: string
  limit?: number
  offset?: number
}

export type AuditNdjsonEvent = {
  type: string
  ts?: string | null
  tenant_id?: string | null
  user_id?: string | null
  trace_id?: string | null
  parent_trace_id?: string | null
  tool_use_id?: string | null
  action?: string | null
  model?: string | null
  input_text?: string | null
  output_text?: string | null
  decision_explain?: string | null
  input_preview?: string | null
  output_preview?: string | null
  error_code?: string | null
  latency_ms?: number | null
  input_tokens?: number | null
  output_tokens?: number | null
  cost?: number | null
}

export type TraceSummary = {
  trace_id: string
  tenant_id: string
  user_id: string
  started_at: string
  actions: string[]
  total_tokens: number
  total_cost: number
  max_latency_ms: number
  error_code: string | null
  row_count: number
}

function toQs(q: AuditQuery): string {
  const p = new URLSearchParams()
  if (q.tenant_id) p.set('tenant_id', q.tenant_id)
  if (q.start) p.set('start', q.start)
  if (q.end) p.set('end', q.end)
  if (q.action) p.set('action', q.action)
  if (q.trace_id) p.set('trace_id', q.trace_id)
  if (q.limit != null) p.set('limit', String(q.limit))
  if (q.offset != null) p.set('offset', String(q.offset))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export async function fetchAuditLogs(q: AuditQuery = {}) {
  return apiGet<AuditLogRow[]>(`/api/audit/logs${toQs(q)}`)
}

export type UsageSummary = {
  period: string
  calls: number
  input_tokens: number
  output_tokens: number
  tokens: number
  cost: number
  daily_limit: number
}

export async function fetchUsageSummary() {
  return apiGet<UsageSummary>('/api/audit/usage-summary')
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

/** NDJSON replay events for trace detail (Task 63). */
export async function fetchAuditNdjsonEvents(
  q: Omit<AuditQuery, 'limit' | 'offset'> = {},
): Promise<AuditNdjsonEvent[]> {
  const qs = toQs({ ...q })
  const sep = qs ? `${qs}&` : '?'
  const res = await apiFetch(`/api/audit/export${sep}format=ndjson`)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `ndjson_export_failed:${res.status}`)
  }
  const body = await res.text()
  const events: AuditNdjsonEvent[] = []
  for (const line of body.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed) continue
    try {
      events.push(JSON.parse(trimmed) as AuditNdjsonEvent)
    } catch {
      // skip malformed lines
    }
  }
  return events
}

/** Group flat audit rows into per-trace summaries for the list view. */
export function groupAuditRowsByTrace(rows: AuditLogRow[]): TraceSummary[] {
  const map = new Map<string, TraceSummary>()
  for (const r of rows) {
    const tid = (r.trace_id || '').trim() || `row-${r.id}`
    const existing = map.get(tid)
    const tokens = (r.input_tokens || 0) + (r.output_tokens || 0)
    const created = r.created_at || ''
    if (!existing) {
      map.set(tid, {
        trace_id: tid,
        tenant_id: r.tenant_id,
        user_id: r.user_id,
        started_at: created,
        actions: r.action ? [r.action] : [],
        total_tokens: tokens,
        total_cost: Number(r.cost || 0),
        max_latency_ms: Number(r.latency_ms || 0),
        error_code: r.error_code || null,
        row_count: 1,
      })
      continue
    }
    if (created && created > existing.started_at) {
      existing.started_at = created
    }
    if (r.action && !existing.actions.includes(r.action)) {
      existing.actions.push(r.action)
    }
    existing.total_tokens += tokens
    existing.total_cost += Number(r.cost || 0)
    existing.max_latency_ms = Math.max(existing.max_latency_ms, Number(r.latency_ms || 0))
    if (r.error_code) existing.error_code = r.error_code
    existing.row_count += 1
  }
  return [...map.values()].sort((a, b) => b.started_at.localeCompare(a.started_at))
}
