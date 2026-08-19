import { apiDelete, apiGet, apiPost } from '@/api/http'

export type FeedbackType = 'helpful' | 'irrelevant' | 'bookmark'

export type SubmitFeedbackBody = {
  session_id: string
  client_message_id: string
  feedback_type: FeedbackType
  rating?: number | null
  comment?: string
  user_message?: string
  bot_response?: string
}

export type FeedbackSubmitResult = {
  feedback_id: number
  session_id: string
  feedback_type: string
  rating: number | null
  client_message_id?: string | null
  created_at: string
}

export type FeedbackMineItem = {
  id: number
  session_id?: string | null
  client_message_id?: string | null
  feedback_type: string
  rating?: number | null
  comment?: string | null
  user_message?: string | null
  bot_response?: string | null
  created_at?: string | null
}

export type FeedbackMineResponse = {
  items: FeedbackMineItem[]
  total: number
}

export async function submitFeedback(
  body: SubmitFeedbackBody,
): Promise<FeedbackSubmitResult> {
  return apiPost<FeedbackSubmitResult>('/feedback/', body)
}

export async function listMyFeedback(opts?: {
  type?: FeedbackType | string
  session_id?: string
  limit?: number
}): Promise<FeedbackMineResponse> {
  const q = new URLSearchParams()
  if (opts?.type) q.set('type', opts.type)
  if (opts?.session_id) q.set('session_id', opts.session_id)
  if (opts?.limit != null) q.set('limit', String(opts.limit))
  const qs = q.toString()
  return apiGet<FeedbackMineResponse>(`/feedback/mine${qs ? `?${qs}` : ''}`)
}

export async function deleteMyFeedback(id: number): Promise<void> {
  await apiDelete(`/feedback/mine/${id}`)
}

/** Strip dig/script markers before copy / bookmark snapshot (P2 / R4).
 * Dig: keep summary only. Script: keep口播正文 (drop markers).
 */
export function cleanBotResponseForFeedback(raw: string): string {
  if (raw.includes('<<<SCRIPT>>>')) {
    const script =
      raw.split('<<<SCRIPT>>>')[1]?.split('<<<END>>>')[0]?.trim() || ''
    if (script) return script
  }
  const withoutDig = raw.includes('<<<DIG>>>')
    ? raw.split('<<<DIG>>>')[0] ?? raw
    : raw
  return withoutDig.replace(/\[查看明细\]/g, '').trim()
}
