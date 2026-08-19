import { apiGet, apiPost } from '@/api/http'

/** POST /chat 非流式 JSON。 */
export type ChatJsonResponse = {
  response: string
  trace_id?: string
  finish_reason?: string
  total_tokens?: number
  total_cost?: number
  pipeline_latency_ms?: number
  error_code?: string | null
  approval_request_id?: string | null
}

export async function postChat(
  message: string,
  opts?: { session_id?: string; user_id?: string },
): Promise<ChatJsonResponse> {
  return apiPost<ChatJsonResponse>('/chat', {
    message,
    session_id: opts?.session_id || 'default',
    user_id: opts?.user_id || 'anonymous',
  })
}

export const CHAT_STREAM_ENDPOINT = '/chat/streaming'

export const WORKSPACE_CHAT_SESSION = 'workspace-chat'

export type ChatHistoryItem = {
  id: number
  role: string
  content: string
  client_message_id?: string | null
  created_at?: string | null
}

export type ChatHistoryResponse = {
  items: ChatHistoryItem[]
  has_more: boolean
}

/** GET /api/chat/history — 47b slice0 + 游标分页 */
export async function fetchChatHistory(
  sessionId: string,
  limit = 10,
  beforeId?: number,
): Promise<ChatHistoryResponse> {
  const q = new URLSearchParams({
    session_id: sessionId,
    limit: String(limit),
  })
  if (beforeId != null) {
    q.set('before_id', String(beforeId))
  }
  return apiGet<ChatHistoryResponse>(`/api/chat/history?${q.toString()}`)
}

/** Persist workspace dig/script bubble into chat history */
export async function postChatNote(body: {
  session_id: string
  content: string
  client_message_id?: string
  role?: 'assistant' | 'user'
}) {
  return apiPost<{ ok: boolean; client_message_id?: string | null }>(
    '/api/chat/notes',
    body,
  )
}
