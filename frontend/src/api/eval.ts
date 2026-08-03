import { apiGet, apiPost } from '@/api/http'

export type EvalItem = {
  id: number
  session_id?: string | null
  user_id?: string | null
  user_message?: string | null
  bot_response?: string | null
  accuracy_score?: number | null
  naturalness_score?: number | null
  safety_score?: number | null
  average_score?: number | null
  overall_comment?: string | null
  is_human_verified?: boolean
  created_at?: string | null
}

export type EvalListResponse = {
  evaluations: EvalItem[]
  total: number
  statistics?: Record<string, unknown> | null
}

export type EvalStatistics = {
  total_count: number
  average_scores: Record<string, number>
  score_ranges?: Record<string, Record<string, number>> | null
}

export type EvalResult = {
  evaluation_id: number
  accuracy_score: number
  naturalness_score: number
  safety_score: number
  average_score: number
  total_score: number
  overall_comment: string
  strengths: string[]
  weaknesses: string[]
  improvement_suggestions: string[]
  created_at: string
}

export async function evaluateOne(body: {
  user_message: string
  bot_response: string
  session_id?: string
  user_id?: string
}) {
  return apiPost<EvalResult>('/evaluation/evaluate', body)
}

export async function evaluateBatch(body: { session_id?: string; limit?: number } = {}) {
  return apiPost<unknown>('/evaluation/batch', body)
}

export async function listEvaluations(opts?: { session_id?: string; limit?: number }) {
  const p = new URLSearchParams()
  if (opts?.session_id) p.set('session_id', opts.session_id)
  if (opts?.limit != null) p.set('limit', String(opts.limit))
  const qs = p.toString()
  return apiGet<EvalListResponse>(`/evaluation/list${qs ? `?${qs}` : ''}`)
}

export async function evalStatistics() {
  return apiGet<EvalStatistics>('/evaluation/statistics')
}
