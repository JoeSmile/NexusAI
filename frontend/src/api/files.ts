import { apiPost } from '@/api/http'

export type SessionUploadResult = {
  attachment_id: string
  status: string
  name?: string
  blocks?: unknown[]
  describe_status?: 'ready' | 'pending' | 'skipped'
  size?: number
}

export async function uploadSessionFile(
  file: File,
  sessionId: string,
): Promise<SessionUploadResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('session_id', sessionId)
  return apiPost<SessionUploadResult>('/api/files', form)
}
