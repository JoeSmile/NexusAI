/** Frontend API — Task 45 content ops / offerings. */

import { apiDelete, apiGet, apiPost, apiPut } from '@/api/http'

export type Offering = {
  id: string
  tenant_id: string
  dept: string
  name: string
  description: string
  status: string
  target_kind: string
  target_id: string
  sort_order: number
  meta?: Record<string, unknown>
}

export type ContentStyle = {
  creator_id?: string
  display_name?: string
  persona?: string
  addressing?: string[]
  catchphrases?: string[]
  avg_sentence_len?: string
  structure_habits?: string[]
  taboos?: string[]
  sample_openers?: string[]
  is_default?: boolean
}

export type HotspotItem = {
  title: string
  summary?: string
  category?: string
  score?: number
  similar_to_previous?: boolean
  /** rich schema (45 enrich) */
  hot_id?: string
  source?: string
  crawl_time?: string
  valid_expire_time?: string
  rank?: number
  hot_score?: number
  hot_trend?: 'up' | 'down' | 'stable' | string | null
  core_topic?: string
  short_desc?: string
  full_summary?: string | null
  main_keywords?: string[]
  extend_keywords?: string[]
  exclude_keywords?: string[]
  target_audience?: {
    primary?: string
    secondary?: string
    age_range?: string
    pain_points?: string[]
  }
  emotion_tag?: string[]
  content_position?: string | null
  suitable_content_type?: string[]
  competition_level?: 'high' | 'medium' | 'low' | string | null
  competitor_angle?: string[]
  differentiate_angle?: string | null
  risk_tag?: string[]
  suggest_limit?: string | null
  reference_material_links?: string[]
  data_support?: string[]
  suggested_opening_hook?: string | null
  /** 顶层中文别名，与 evidence.raw_excerpt 同值 */
  原文摘录?: string
  evidence?: {
    source_kind?: string
    source_label?: string
    raw_excerpt?: string
    crawl_note?: string
    source_url?: string
  }
}

export async function listOfferings(dept?: string) {
  const q = dept ? `?dept=${encodeURIComponent(dept)}` : ''
  return apiGet<{ items: Offering[]; count: number }>(`/api/offerings${q}`)
}

export async function listStyles() {
  return apiGet<{ items: ContentStyle[]; default_creator_id: string }>(
    '/api/content/styles',
  )
}

export async function upsertStyle(creatorId: string, body: Partial<ContentStyle>) {
  return apiPut<{ style: ContentStyle }>(
    `/api/content/styles/${encodeURIComponent(creatorId)}`,
    body,
  )
}

export async function extractStyle(creatorId: string, text: string, save = true) {
  return apiPost<{ style: ContentStyle }>(
    `/api/content/styles/${encodeURIComponent(creatorId)}/extract`,
    { text, save, creator_id: creatorId },
  )
}

/** Per-creator speech file → re-parse style. Not company RAG upload. */
export async function uploadStyleSpeech(creatorId: string, file: File) {
  const fd = new FormData()
  fd.append('file', file)
  return apiPost<{
    style: ContentStyle
    chars: number
    filename: string
    reparsed: boolean
  }>(`/api/content/styles/${encodeURIComponent(creatorId)}/upload`, fd)
}

export async function deleteStyle(creatorId: string) {
  return apiDelete<{ deleted: boolean }>(
    `/api/content/styles/${encodeURIComponent(creatorId)}`,
  )
}

export async function getOrgProfile() {
  return apiGet<{ profile: Record<string, unknown> }>('/api/content/org-profile')
}

export async function putOrgProfile(profile: Record<string, unknown>) {
  return apiPut<{ profile: Record<string, unknown> }>(
    '/api/content/org-profile',
    profile,
  )
}

export async function digHotspots(body: {
  adapter?: string
  categories?: string[]
  keywords?: string
  exclude_keywords?: string
  paste_text?: string
  industry?: string
  region?: string
  use_org_profile?: boolean
  user_note?: string
  save?: boolean
}) {
  return apiPost<{
    adapter: string
    items: HotspotItem[]
    content_hash: string
    count: number
    artifact_id?: string
    day_artifact_id?: string
    run_artifact_id?: string
    new_count?: number
    skipped_duplicates?: number
    idempotent?: boolean
    day?: string
    dig_evidence?: Record<string, unknown>
  }>('/api/content/hotspots/dig', body)
}

export async function generateTopicBrief(body: { title: string; summary?: string }) {
  return apiPost<{
    kind: string
    title: string
    summary?: string
    background?: string
    key_points?: string[]
    risks?: string[]
    bilibili?: unknown[]
    artifact_id?: string | null
  }>('/api/content/topics/brief', body)
}

export async function generateScript(body: {
  creator_id?: string
  hotspots?: HotspotItem[]
  duration_sec?: number
  platform?: string
  extra_instruction?: string
  student_names?: string[]
  save?: boolean
  brief?: Record<string, unknown>
}) {
  return apiPost<{
    script: string
    student_pii_redacted?: boolean
    style_is_default?: boolean
    artifact_id?: string
  }>('/api/content/scripts/generate', body)
}

export type ContentArtifactItem = {
  id: string
  kind: string
  title: string
  body: unknown
  created_at?: string
  creator_id?: string | null
  owner_user_id?: string
  visibility?: 'private' | 'shared'
  is_owner?: boolean
}

export async function listArtifacts(kind?: string) {
  const q = kind ? `?kind=${encodeURIComponent(kind)}` : ''
  return apiGet<{
    items: ContentArtifactItem[]
    count: number
  }>(`/api/content/artifacts${q}`)
}

export async function setArtifactVisibility(
  artifactId: string,
  visibility: 'private' | 'shared',
) {
  return apiPost<ContentArtifactItem>(
    `/api/content/artifacts/${encodeURIComponent(artifactId)}/visibility`,
    { visibility },
  )
}

export async function excludeHotspot(title: string) {
  return apiPost<{
    ok: boolean
    title: string
    remaining: number
    excluded_count: number
  }>('/api/content/hotspots/exclude', { title })
}
