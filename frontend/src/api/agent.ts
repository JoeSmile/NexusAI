import { apiGet, apiPost } from '@/api/http'

export type AgentEnvelope<T> = {
  code: number
  message: string
  data: T
}

export type AgentTool = {
  name?: string
  description?: string
  [k: string]: unknown
}

export async function agentStatus() {
  return apiGet<AgentEnvelope<Record<string, unknown>>>('/agent/status')
}

export async function agentTools() {
  return apiGet<AgentEnvelope<AgentTool[] | Record<string, unknown>>>('/agent/tools')
}

export async function agentChat(body: {
  user_id: string
  message: string
  conversation_id?: string
}) {
  return apiPost<AgentEnvelope<Record<string, unknown>>>('/agent/chat', body)
}

export async function agentHistory(userId: string, limit = 10) {
  return apiGet<AgentEnvelope<unknown[]>>(
    `/agent/history/${encodeURIComponent(userId)}?limit=${limit}`,
  )
}
