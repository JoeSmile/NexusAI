import { apiDelete, apiGet, apiPatch, apiPost } from '@/api/http'

export type OrgUnit = {
  id: string
  tenant_id: string
  parent_id: string | null
  name: string
  path: string
  deleted_at: string | null
  created_at: string | null
}

export type OrgMembership = {
  id: string
  tenant_id: string
  user_id: string
  org_unit_id: string
  is_primary: boolean
  business_roles: string[]
  created_at: string | null
}

export function fetchOrgTree(includeDeleted = false) {
  const q = includeDeleted ? '?include_deleted=1' : ''
  return apiGet<OrgUnit[]>(`/api/org/units/tree${q}`)
}

export function createOrgUnit(body: { name: string; parent_id?: string | null }) {
  return apiPost<OrgUnit>('/api/org/units', body)
}

export function moveOrgUnit(id: string, parent_id: string | null) {
  return apiPatch<OrgUnit>(`/api/org/units/${id}/move`, { parent_id })
}

export function deleteOrgUnit(id: string) {
  return apiDelete<{ status: string; mode?: string; id: string }>(
    `/api/org/units/${id}`,
  )
}

export function fetchMyMemberships() {
  return apiGet<OrgMembership[]>('/api/org/memberships/me')
}

export function fetchUnitMemberships(unitId: string) {
  return apiGet<OrgMembership[]>(`/api/org/units/${unitId}/memberships`)
}

export function upsertMembership(body: {
  user_id: string
  org_unit_id: string
  is_primary?: boolean
  business_roles?: string[]
}) {
  return apiPost<OrgMembership>('/api/org/memberships', body)
}

export function deleteMembership(id: string) {
  return apiDelete<{ status: string; id: string }>(`/api/org/memberships/${id}`)
}
