import type { AuditLogRow, AuditNdjsonEvent } from '@/api/audit'

export type RagSanitizeSnapshot = {
  rag_retrieved_ids: string[]
  flags: Record<string, number>
  redacted_fragments: number
}

export type MemoryTraceEvent = {
  action: string
  ts?: string | null
  input_preview?: string
  output_preview?: string
  error_code?: string | null
}

export type MemoryTraceSnapshot = {
  source: 'audit_replay'
  rag: RagSanitizeSnapshot | null
  events: MemoryTraceEvent[]
  action_labels: string[]
}

const MEMORY_ACTIONS = new Set([
  'memory.rag_sanitize',
  'memory.write_async',
  'memory.bind_pending',
  'memory.reject_item',
  'memory.dropped',
  'memory.update',
  'memory.delete',
])

function parseRagSanitizePayload(raw: string | null | undefined): RagSanitizeSnapshot | null {
  if (!raw?.trim()) return null
  try {
    const data = JSON.parse(raw) as {
      rag_retrieved_ids?: unknown
      flags?: unknown
      redacted_fragments?: unknown
    }
    const ids = Array.isArray(data.rag_retrieved_ids)
      ? data.rag_retrieved_ids.map((x) => String(x))
      : []
    const flags =
      data.flags && typeof data.flags === 'object' && !Array.isArray(data.flags)
        ? (data.flags as Record<string, number>)
        : {}
    const redacted =
      typeof data.redacted_fragments === 'number' ? data.redacted_fragments : 0
    return {
      rag_retrieved_ids: ids,
      flags,
      redacted_fragments: redacted,
    }
  } catch {
    return null
  }
}

/** Lightweight memory trace view — parsed from audit NDJSON (no trace-level memory API). */
export function parseMemorySnapshotFromAudit(
  events: AuditNdjsonEvent[],
  rows: AuditLogRow[] = [],
): MemoryTraceSnapshot | null {
  const memoryEvents: MemoryTraceEvent[] = []

  for (const ev of events) {
    const action = ev.action || ''
    if (!action.startsWith('memory.') && ev.type !== 'memory_event') continue
    memoryEvents.push({
      action: action || 'memory',
      ts: ev.ts,
      input_preview: ev.input_preview || ev.input_text || undefined,
      output_preview: ev.output_preview || ev.output_text || undefined,
      error_code: ev.error_code,
    })
  }

  for (const row of rows) {
    if (!MEMORY_ACTIONS.has(row.action)) continue
    if (memoryEvents.some((e) => e.action === row.action && e.ts === row.created_at)) {
      continue
    }
    memoryEvents.push({
      action: row.action,
      ts: row.created_at,
      error_code: row.error_code,
    })
  }

  if (!memoryEvents.length) return null

  memoryEvents.sort((a, b) => String(a.ts || '').localeCompare(String(b.ts || '')))

  const ragEvent = memoryEvents.find((e) => e.action === 'memory.rag_sanitize')
  const rag = parseRagSanitizePayload(ragEvent?.output_preview)

  return {
    source: 'audit_replay',
    rag,
    events: memoryEvents,
    action_labels: [...new Set(memoryEvents.map((e) => e.action))],
  }
}
