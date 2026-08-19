import { apiGet } from '@/api/http'

export type AvailableModelItem = {
  model: string
  series: string
  configured?: boolean
}

export type AvailableModelsResponse = {
  items: AvailableModelItem[]
}

export async function listAvailableModels() {
  return apiGet<AvailableModelsResponse>('/api/llm/available-models')
}

/** 粘贴预览：前后各 6 位，中间 ***（明文只放 ref，不进 React state） */
export function maskApiKeyPreview(raw: string, edge = 6): string {
  const s = raw.trim()
  if (!s) return ''
  if (s.length <= edge * 2) return `${s.slice(0, 1)}***${s.slice(-1)}`
  return `${s.slice(0, edge)}***${s.slice(-edge)}`
}

/** Embedding 凭证固定维度（与 pgvector 列一致） */
export const EMBEDDING_DIMENSIONS = 1536

/** 编辑态 Key 输入框占位（不暗示可打字明文） */
export const API_KEY_EDIT_PLACEHOLDER = '***********'
