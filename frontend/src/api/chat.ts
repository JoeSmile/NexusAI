import { apiPost } from '@/api/http'

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
