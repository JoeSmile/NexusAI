import { apiGet, apiPost } from '@/api/http'

export const USER_AGREEMENT_KIND = 'user_agreement'

export type TermsDoc = {
  id: number
  version: string
  kind: string
  effective_at?: string | null
  content_md: string
}

export async function fetchTermsCurrent(kind: string) {
  return apiGet<TermsDoc>(`/api/terms/current?kind=${encodeURIComponent(kind)}`, {
    skipAuth: true,
  })
}

export async function fetchTermsPending() {
  return apiGet<{ pending: TermsDoc[] }>('/api/terms/pending')
}

export async function acceptTerms(kind: string, version: string) {
  return apiPost<{ tenant_id: string; user_id: string; kind: string; version: string }>(
    '/api/terms/accept',
    { kind, version },
  )
}
