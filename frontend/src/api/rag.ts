import { apiDelete, apiGet, apiPost } from '@/api/http'

export type RagAskData = {
  answer?: string
  sources?: unknown[]
  question?: string
  knowledge_count?: number
  cache_hit?: boolean
  latency_ms?: number
}

export type RagStatusData = {
  status?: string
  document_count?: number
  cache?: {
    hit?: number
    miss?: number
    hit_ratio?: number
    l1_hit?: number
    l2_hit?: number
    enabled?: boolean
  }
}

export async function ragAsk(question: string, search_k = 3) {
  return apiPost<{ success: boolean; data: RagAskData }>('/api/rag/ask', {
    question,
    search_k,
  })
}

export async function ragSearch(query: string, k = 5) {
  return apiPost<{
    success: boolean
    data: { query: string; results: unknown[]; count: number }
  }>('/api/rag/search', { query, k })
}

export async function ragStatus() {
  return apiGet<{ success: boolean; data: RagStatusData }>('/api/rag/status')
}

/** POST /api/rag/upload/pdf — multipart FormData field name = file */
export async function ragUploadPdf(file: File) {
  const fd = new FormData()
  fd.append('file', file)
  return apiPost<{
    success: boolean
    message: string
    data: RagStatusData
  }>('/api/rag/upload/pdf', fd)
}

export type RagDocumentItem = {
  source: string
  name: string
  source_type: string
  chunk_count: number
  created_at?: string | null
}

export async function ragListDocuments() {
  return apiGet<{
    success: boolean
    data: { items: RagDocumentItem[]; count: number }
  }>('/api/rag/documents')
}

export async function ragDeleteDocument(source: string) {
  const q = `?source=${encodeURIComponent(source)}`
  return apiDelete<{
    success: boolean
    message: string
    data: { deleted: number; source: string }
  }>(`/api/rag/documents${q}`)
}
