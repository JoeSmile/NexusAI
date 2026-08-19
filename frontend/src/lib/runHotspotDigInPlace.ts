/**
 * In-place hotspot dig via workflow start_run + poll (45b slice 3).
 * With form params (or no published workflow) → POST /api/content/hotspots/dig.
 */
import {
  digHotspots,
  listOfferings,
  type HotspotItem,
} from '@/api/contentOps'
import { listWorkflows } from '@/api/workflows'
import { getRun, getRunNodes, startRun } from '@/api/workflowRuns'
import type { HotspotDigFormValues } from '@/components/agent/HotspotDigDialog'

const BUILTIN_NAME = '内置·抓取相关热点'
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'suspended'])

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms))
}

function findItems(node: unknown, depth = 5): HotspotItem[] | null {
  if (!node || typeof node !== 'object' || depth <= 0) return null
  const o = node as Record<string, unknown>
  if (Array.isArray(o.items)) return o.items as HotspotItem[]
  for (const v of Object.values(o)) {
    const found = findItems(v, depth - 1)
    if (found) return found
  }
  return null
}

function countFromNodes(nodes: Array<{ output?: unknown }>): {
  count: number
  items: HotspotItem[]
} {
  for (const n of nodes) {
    const found = findItems(n.output)
    if (found) {
      return { count: found.length, items: found }
    }
  }
  return { count: 0, items: [] }
}

export async function resolveHotspotWorkflowId(): Promise<string | null> {
  try {
    await listOfferings('content_growth')
  } catch {
    /* seed best-effort */
  }
  const wf = await listWorkflows({ status: 'published', limit: 50 })
  const hit =
    (wf.items || []).find((w) => w.name === BUILTIN_NAME) ||
    (wf.items || []).find((w) =>
      (w.ir?.nodes || []).some((n) => n.capability_id === 'hotspot.dig'),
    )
  return hit?.id ?? null
}

export type DigProgressHandlers = {
  onProgress: (text: string) => void
  onDone: (payload: {
    count: number
    items: HotspotItem[]
    runId?: string
    via: 'workflow' | 'direct'
    digEvidence?: Record<string, unknown>
    form?: HotspotDigFormValues
  }) => void
  onError: (message: string) => void
  /** AbortSignal — stop polling only; does not cancel server run */
  signal?: AbortSignal
  /** 表单参数：有则走直接 dig（workflow start_run 暂不透传表单） */
  form?: HotspotDigFormValues
}

async function digDirect(
  form: HotspotDigFormValues | undefined,
  onDone: DigProgressHandlers['onDone'],
) {
  const dig = await digHotspots({
    adapter: 'topic_agent',
    save: true,
    categories: form?.categories,
    keywords: form?.keywords,
    exclude_keywords: form?.exclude_keywords,
    industry: form?.industry,
    region: form?.region,
    use_org_profile: form?.use_org_profile ?? true,
    user_note: form?.user_note,
  })
  onDone({
    count: dig.count ?? dig.items?.length ?? 0,
    items: dig.items || [],
    via: 'direct',
    digEvidence: dig.dig_evidence,
    form,
  })
}

export async function runHotspotDigInPlace(handlers: DigProgressHandlers): Promise<void> {
  const { onProgress, onDone, onError, signal, form } = handlers
  const aborted = () => signal?.aborted

  try {
    // 侧栏/空态确认表单后：必须带条件 dig，不能丢进无参 workflow
    if (form) {
      onProgress('⏳ 正在按条件抓取热点…')
      await digDirect(form, onDone)
      return
    }

    const wfId = await resolveHotspotWorkflowId()
    if (wfId) {
      onProgress('⏳ 正在启动抓取热点工作流…')
      const run = await startRun(wfId)
      const runId = run.id
      onProgress(`⏳ 正在抓取热点…（run ${runId.slice(0, 8)}）`)

      for (let i = 0; i < 90; i++) {
        if (aborted()) return
        await sleep(1000)
        if (aborted()) return
        const cur = await getRun(runId)
        if (!TERMINAL.has(cur.status)) continue
        if (cur.status !== 'succeeded') {
          onError(cur.error_message || cur.error_code || `运行失败：${cur.status}`)
          return
        }
        const nodes = await getRunNodes(runId)
        const { count, items } = countFromNodes(nodes.items || [])
        onDone({
          count: count || items.length,
          items,
          runId,
          via: 'workflow',
        })
        return
      }
      onError('抓取超时，请稍后在内容库查看是否已入库')
      return
    }

    onProgress('⏳ 未找到已发布工作流，改为直接挖掘…')
    await digDirect(undefined, onDone)
  } catch (e) {
    onError(e instanceof Error ? e.message : String(e))
  }
}
