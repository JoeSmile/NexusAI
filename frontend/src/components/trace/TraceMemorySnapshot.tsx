import type { MemoryTraceSnapshot } from '@/lib/memorySnapshot'

type Props = {
  snapshot: MemoryTraceSnapshot | null
}

export function TraceMemorySnapshot({ snapshot }: Props) {
  if (!snapshot) {
    return (
      <p className="text-muted-foreground text-xs">
        本 trace 无 memory 审计事件（未走 load_memory / rag_sanitize，或审计未写入）
      </p>
    )
  }

  const { rag, events } = snapshot

  return (
    <div className="space-y-3 text-xs">
      <p className="text-muted-foreground">
        来源：审计回放（轻量方案）— 非完整 hot/warm/cold 快照
      </p>

      {rag ? (
        <div className="rounded-md border border-border/60 bg-muted/20 p-2">
          <p className="font-medium">RAG 召回（rag_sanitize）</p>
          {rag.rag_retrieved_ids.length ? (
            <ul className="mt-1 list-inside list-disc font-mono">
              {rag.rag_retrieved_ids.map((id) => (
                <li key={id}>{id}</li>
              ))}
            </ul>
          ) : (
            <p className="text-muted-foreground mt-1">无召回文档 ID</p>
          )}
          {Object.keys(rag.flags).length ? (
            <p className="text-muted-foreground mt-1">
              清洗标记: {JSON.stringify(rag.flags)}
            </p>
          ) : null}
          {rag.redacted_fragments > 0 ? (
            <p className="mt-1 text-amber-600">
              已脱敏片段: {rag.redacted_fragments}
            </p>
          ) : null}
        </div>
      ) : null}

      <div>
        <p className="font-medium">Memory 审计事件 ({events.length})</p>
        <ul className="mt-1 max-h-40 space-y-1 overflow-y-auto">
          {events.map((ev, idx) => (
            <li
              key={`${ev.action}-${ev.ts}-${idx}`}
              className="rounded border border-border/50 px-2 py-1"
            >
              <span className="font-medium">{ev.action}</span>
              {ev.ts ? (
                <span className="text-muted-foreground"> · {ev.ts}</span>
              ) : null}
              {ev.error_code ? (
                <span className="text-red-600"> · {ev.error_code}</span>
              ) : null}
              {ev.output_preview ? (
                <p className="text-muted-foreground mt-0.5 line-clamp-2 break-all">
                  {ev.output_preview}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
