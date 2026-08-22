import { apiFetch, apiGet, apiPost } from '@/api/http'

export type UsageSummary = {
  tenant_id: string | null
  billing_month: string | null
  credential_kind: string | null
  totals: {
    calls: number
    input_tokens: number
    output_tokens: number
    cost: number
  }
  by_model: Array<{
    model: string
    credential_kind: string
    calls: number
    input_tokens: number
    output_tokens: number
    cost: number
  }>
}

export type UsageDetailRow = {
  id: number
  tenant_id: string
  user_id: string
  trace_id?: string | null
  credential_kind: string
  key_id?: string | null
  model: string
  provider: string
  input_tokens: number
  output_tokens: number
  cost: number
  currency: string
  billing_month: string
  created_at?: string | null
}

export type UsageQuery = {
  tenant_id?: string
  billing_month?: string
  credential_kind?: string
  model?: string
  limit?: number
  offset?: number
}

function toQs(q: UsageQuery): string {
  const p = new URLSearchParams()
  if (q.tenant_id) p.set('tenant_id', q.tenant_id)
  if (q.billing_month) p.set('billing_month', q.billing_month)
  if (q.credential_kind) p.set('credential_kind', q.credential_kind)
  if (q.model) p.set('model', q.model)
  if (q.limit != null) p.set('limit', String(q.limit))
  if (q.offset != null) p.set('offset', String(q.offset))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export async function fetchUsageSummary(q: UsageQuery = {}) {
  return apiGet<UsageSummary>(`/api/billing/usage/summary${toQs(q)}`)
}

export async function fetchUsageDetail(q: UsageQuery = {}) {
  return apiGet<UsageDetailRow[]>(`/api/billing/usage/detail${toQs(q)}`)
}

export async function exportUsageCsv(q: UsageQuery = {}) {
  const res = await apiFetch(`/api/billing/usage/export${toQs(q)}`)
  if (!res.ok) throw new Error(`export failed: ${res.status}`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `usage_${q.billing_month || 'all'}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export type WalletSummary = {
  tenant_id: string
  balance: number
  currency: string
  updated_at?: string | null
  transactions: Array<{
    id: number
    type: string
    amount: number
    balance_after: number
    method: string
    reference_no?: string | null
    operator?: string | null
    created_at?: string | null
  }>
}

export async function fetchWallet(limit = 20) {
  return apiGet<WalletSummary>(`/api/billing/wallet?limit=${limit}`)
}

export async function rechargeWallet(amount: number, referenceNo: string) {
  return apiPost<{
    tenant_id: string
    amount: number
    balance_after: number
    reference_no: string
    method: string
  }>('/api/billing/wallet/recharge', {
    amount,
    reference_no: referenceNo,
    method: 'manual',
  })
}
