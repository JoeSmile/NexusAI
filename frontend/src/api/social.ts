/** Frontend API — Task 52 social benchmark (TikHub). */

import { apiFetch, apiGet, apiPost } from '@/api/http'

export type SocialPlatform =
  | 'douyin'
  | 'wechat_channels'
  | 'wechat_mp'
  | 'xiaohongshu'

export type SocialAccountCard = {
  id: number
  platform: string
  account_key: string
  external_id?: string | null
  nickname?: string | null
  avatar_url?: string | null
  follower_count?: number | null
  total_favorited?: number | null
  content_count?: number | null
}

export type SocialTask = {
  id: number
  tenant_id: string
  user_id: string
  platform: string
  account_id: number
  status: string
  progress: number
  total_count: number
  new_count: number
  skipped: number
  retry_count?: number
  error?: string | null
  created_at?: string | null
  finished_at?: string | null
  created?: boolean
  hint_previous_task_id?: number | null
  results?: SocialResultRow[]
  stage?: 'idle' | 'fetching' | 'fetched' | 'analyzing' | 'analyzed' | 'failed'
  result_count?: number
}

export type SocialResultRow = {
  content_id: number
  template_id?: number | null
  structure_json?: Record<string, unknown> | null
  replica_json?: Record<string, unknown> | null
}

export type SocialContent = {
  id: number
  platform: string
  account_id: number
  external_id: string
  title?: string | null
  content?: string | null
  content_source?: string | null
  duration_s?: number | null
  like_count?: number | null
  comment_count?: number | null
  share_count?: number | null
  collect_count?: number | null
  published_at?: string | null
  fetched_at?: string | null
}

export type SocialReplica = {
  stub?: boolean
  titles?: string[]
  script?: string
  tags?: string[]
  brand?: Record<string, string>
}

export async function probeSocialAccount(body: {
  platform: string
  account_key: string
}) {
  return apiPost<SocialAccountCard>('/api/social/probe', body)
}

export async function listSocialFollows() {
  return apiGet<{ items: SocialAccountCard[] }>('/api/social/follows')
}

export async function startSocialAnalysis(body: {
  platform: string
  account_key: string
  phase?: 'fetch' | 'analyze' | 'full'
  fetch_limit?: number
}) {
  return apiPost<SocialTask>('/api/social/analysis-tasks', body)
}

export async function getSocialTask(taskId: number) {
  return apiGet<SocialTask>(`/api/social/analysis-tasks/${taskId}`)
}

export async function retrySocialTask(taskId: number) {
  return apiPost<SocialTask>(`/api/social/analysis-tasks/${taskId}/retry`, {})
}

export async function listSocialContents(params: {
  account_id: number
  like_min?: number
  collect_min?: number
  duration_min?: number
  duration_max?: number
  date_from?: string
  date_to?: string
  has_content?: boolean
}) {
  const q = new URLSearchParams()
  q.set('account_id', String(params.account_id))
  if (params.like_min != null) q.set('like_min', String(params.like_min))
  if (params.collect_min != null) q.set('collect_min', String(params.collect_min))
  if (params.duration_min != null) q.set('duration_min', String(params.duration_min))
  if (params.duration_max != null) q.set('duration_max', String(params.duration_max))
  if (params.date_from) q.set('date_from', params.date_from)
  if (params.date_to) q.set('date_to', params.date_to)
  if (params.has_content != null) q.set('has_content', String(params.has_content))
  return apiGet<{ items: SocialContent[] }>(`/api/social/contents?${q}`)
}

export async function exportSocialXlsx(taskId: number) {
  const res = await apiFetch(`/api/social/export/${taskId}.xlsx`)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `export_failed:${res.status}`)
  }
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') || ''
  const m = /filename=([^;]+)/i.exec(cd)
  const filename = (m?.[1] || `social_${taskId}.xlsx`).replace(/"/g, '')
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export async function replicaSocialContent(
  contentId: number,
  body: {
    task_id: number
    brand?: { name?: string; business?: string; style?: string; audience?: string }
  },
) {
  return apiPost<{
    content_id: number
    task_id: number
    replica: SocialReplica
  }>(`/api/social/contents/${contentId}/replica`, body)
}

export async function replicaSocialBatch(body: {
  content_ids: number[]
  task_id: number
  brand?: { name?: string; business?: string; style?: string; audience?: string }
}) {
  return apiPost<{ items: Array<{ content_id: number; replica: SocialReplica }> }>(
    '/api/social/replica-batch',
    body,
  )
}
