/** Query rewrite + coref table card for TraceConsole (Task 65 slice 7). */
import type { AuditNdjsonEvent } from '@/api/audit'

type CorefEntry = {
  entity_id: string
  canonical: string
  mentions?: string[]
  resolved_value: string
  confidence?: number
}

type RewriteExplain = {
  query_rewrite?: {
    rewritten_query?: string
    sub_queries?: string[]
    coref_table?: { entries?: CorefEntry[] }
  }
  coref_table?: { entries?: CorefEntry[] }
}

function parseRewriteExplain(ev: AuditNdjsonEvent): RewriteExplain | null {
  if (!ev.decision_explain) return null
  try {
    return JSON.parse(ev.decision_explain) as RewriteExplain
  } catch {
    return null
  }
}

type Props = {
  events: AuditNdjsonEvent[]
}

export function TraceRewriteCard({ events }: Props) {
  const row = events.find((e) => e.action === 'chat.task_plan')
  if (!row) return null
  const parsed = parseRewriteExplain(row)
  const qr = parsed?.query_rewrite
  if (!qr?.rewritten_query) return null
  const coref =
    qr.coref_table?.entries?.length
      ? qr.coref_table.entries
      : parsed?.coref_table?.entries || []

  return (
    <section className="space-y-2 rounded-md border border-border/60 p-3">
      <h3 className="text-sm font-semibold">Query 重写 · 指代消解</h3>
      <div className="text-xs space-y-2">
        <div>
          <span className="text-muted-foreground">rewritten_query：</span>
          <span className="break-all">{qr.rewritten_query}</span>
        </div>
        {coref.length > 0 ? (
          <div>
            <p className="text-muted-foreground mb-1">coref_table</p>
            <ul className="space-y-1">
              {coref.map((e) => (
                <li key={e.entity_id} className="rounded bg-muted/40 px-2 py-1">
                  <span className="font-medium">{e.entity_id}</span>
                  {' → '}
                  {e.resolved_value || e.canonical}
                  {e.mentions?.length ? (
                    <span className="text-muted-foreground">
                      {' '}
                      (mentions: {e.mentions.join(', ')})
                    </span>
                  ) : null}
                  {e.confidence != null ? (
                    <span className="text-muted-foreground"> · conf {e.confidence}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-muted-foreground">无 coref 条目</p>
        )}
      </div>
    </section>
  )
}
