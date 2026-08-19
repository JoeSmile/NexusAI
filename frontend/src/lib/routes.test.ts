import { describe, expect, it } from 'vitest'

import { HOME_PATH, PANEL_REDIRECTS, resolvePostLoginPath } from '@/lib/routes'

describe('product routes (AgentUI shell)', () => {
  it('maps legacy panels to workspace/admin', () => {
    expect(PANEL_REDIRECTS['/panels/chat']).toBe('/workspace')
    expect(PANEL_REDIRECTS['/panels/admin']).toBe('/admin/keys')
    expect(PANEL_REDIRECTS['/panels/rag']).toBe('/workspace/knowledge')
  })

  it('resolvePostLoginPath prefers next and remaps legacy', () => {
    expect(resolvePostLoginPath(null)).toBe(HOME_PATH)
    expect(resolvePostLoginPath('/panels/chat')).toBe('/workspace')
    expect(resolvePostLoginPath('/governance/org')).toBe('/admin/org')
  })
})
