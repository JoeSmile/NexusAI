"""Frontend API — Task 45 content ops / offerings."""

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
  paste_text?: string
  save?: boolean
}) {
  return apiPost<{
    adapter: string
    items: HotspotItem[]
    content_hash: string
    count: number
    artifact_id?: string
  }>('/api/content/hotspots/dig', body)
}

export async function generateScript(body: {
  creator_id?: string
  hotspots?: HotspotItem[]
  duration_sec?: number
  platform?: string
  extra_instruction?: string
  student_names?: string[]
  save?: boolean
}) {
  return apiPost<{
    script: string
    student_pii_redacted?: boolean
    style_is_default?: boolean
    artifact_id?: string
  }>('/api/content/scripts/generate', body)
}

export async function listArtifacts(kind?: string) {
  const q = kind ? `?kind=${encodeURIComponent(kind)}` : ''
  return apiGet<{
    items: Array<{
      id: string
      kind: string
      title: string
      body: unknown
      created_at?: string
    }>
    count: number
  }>(`/api/content/artifacts${q}`)
}
