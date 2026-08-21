import { apiDelete, apiGet, apiPatch } from '@/api/http'

export type WarmMemory = {
  id: string
  content: string
  key: string
  value: string
  importance?: number
  type?: string
  updated_at?: string | null
}

export type MyMemoriesResponse = {
  user_id: string
  tenant_id: string
  memories: WarmMemory[]
  total: number
}

export async function listMyMemories(limit = 200) {
  return apiGet<MyMemoriesResponse>(`/memory/me/memories?limit=${limit}`)
}

export async function patchMyMemory(memoryId: string, value: string) {
  return apiPatch<{ message: string; memory_id: string }>(
    `/memory/me/memories/${encodeURIComponent(memoryId)}`,
    { value },
  )
}

export async function deleteMyMemory(memoryId: string) {
  return apiDelete<{ message: string; memory_id: string }>(
    `/memory/me/memories/${encodeURIComponent(memoryId)}`,
  )
}
