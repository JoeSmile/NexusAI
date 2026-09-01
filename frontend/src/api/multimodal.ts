/** @deprecated Task 58 legacy vision chat. HomeChat uses POST /api/files (76b). */

import { apiFetch } from '@/api/http'

export type MultimodalChatResponse = {
  response: string
  session_id: string
  context?: {
    trace_id?: string
    model?: string
    file_id?: string
    image_hash?: string
    modality?: string
  }
}

export async function postMultimodalChat(
  file: File,
  text: string,
  opts?: { model?: string; session_id?: string },
): Promise<MultimodalChatResponse> {
  const form = new FormData()
  form.append('file', file)
  form.append('text', text)
  if (opts?.model) form.append('model', opts.model)
  form.append('session_id', opts?.session_id || 'default')

  const res = await apiFetch('/api/multimodal/chat', {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    const detail = (data as { detail?: { code?: string; message?: string } }).detail
    const code = detail?.code || 'SYS_001'
    const message = detail?.message || res.statusText
    throw new Error(`[${code}] ${message}`)
  }
  return res.json() as Promise<MultimodalChatResponse>
}
