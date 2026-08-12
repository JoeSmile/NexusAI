import { describe, expect, it } from 'vitest'

import { KEYS_ROLES, ORG_ROLES, roleAllowed } from '@/lib/navAccess'

describe('navAccess role guards', () => {
  it('org allows admin roles only', () => {
    expect(roleAllowed('user', ORG_ROLES)).toBe(false)
    expect(roleAllowed('tenant_admin', ORG_ROLES)).toBe(true)
    expect(roleAllowed('auditor', ORG_ROLES)).toBe(true)
  })

  it('keys excludes auditor and user', () => {
    expect(roleAllowed('auditor', KEYS_ROLES)).toBe(false)
    expect(roleAllowed('user', KEYS_ROLES)).toBe(false)
    expect(roleAllowed('super_admin', KEYS_ROLES)).toBe(true)
  })
})
