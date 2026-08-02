import { apiGet, apiPost } from '@/api/http'

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
