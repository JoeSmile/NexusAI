import { ChevronDown, ChevronUp, Loader2 } from 'lucide-react'
import { useState } from 'react'

import type { ExecutionState, ExecutionStepStatus } from '@/hooks/sseParse'

type Props = {
  execution: ExecutionState | null
  className?: string
}

const STATUS_LABEL: Record<ExecutionStepStatus, string> = {
  pending: '待执行',
  running: '执行中',
  succeeded: '完成',
  failed: '失败',
  skipped: '跳过',
}

const CAPABILITY_LABEL: Record<string, string> = {
  'task.plan': '规划任务',
  'rag.search': '检索公司知识库',
  'rag.ask': '检索公司知识库',
  'web.search': '检索全网资料',
  'llm.generate': '生成文案',
  'script.gen': '生成口播稿',
  'hotspot.dig': '抓取热点',
}

export function capabilityLabel(capabilityId: string): string {
  return CAPABILITY_LABEL[capabilityId] || capabilityId
}

function statusClass(status: ExecutionStepStatus): string {
  switch (status) {
    case 'running':
      return 'text-blue-600'
    case 'succeeded':
      return 'text-emerald-600'
    case 'failed':
      return 'text-red-600'
    case 'skipped':
      return 'text-amber-600'
    default:
      return 'text-muted-foreground'
  }
}

export function ExecutionPanel({ execution, className = '' }: Props) {
  const [open, setOpen] = useState(true)
  if (!execution || execution.steps.length === 0) return null

  const active = execution.activeTool

  return (
    <section
      className={`mb-3 rounded-lg border border-border/70 bg-muted/30 text-sm ${className}`}
      data-testid="execution-panel"
    >
      {active ? (
        <div
          className="flex items-center gap-2 border-b border-border/60 bg-blue-50/80 px-3 py-2 text-blue-900"
          data-testid="execution-active-tool"
        >
          <Loader2 size={14} className="animate-spin shrink-0" />
          <span>
            正在调用 <strong>{capabilityLabel(active.label)}</strong>
            {active.capabilityId && active.capabilityId !== active.label
              ? ` (${active.capabilityId})`
              : ''}
            …
          </span>
        </div>
      ) : null}
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left font-medium"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span>执行计划{execution.goal ? ` · ${execution.goal}` : ''}</span>
        {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>
      {open ? (
        <ul className="space-y-2 border-t border-border/60 px-3 py-2">
          {execution.steps.map((step) => (
            <li
              key={step.id}
              className="rounded-md border border-border/50 bg-background/80 px-2 py-1.5"
            >
              <div className="flex items-center gap-2">
                {step.status === 'running' ? (
                  <Loader2 size={14} className="animate-spin text-blue-600" />
                ) : null}
                <span className="font-mono text-xs text-muted-foreground">{step.id}</span>
                <span className="text-xs">{capabilityLabel(step.capability_id)}</span>
                <span className={`ml-auto text-xs ${statusClass(step.status)}`}>
                  {STATUS_LABEL[step.status]}
                </span>
              </div>
              {step.summary ? (
                <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{step.summary}</p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
