import { describe, expect, it } from 'vitest'

import { HOME_PATH, PANEL_REDIRECTS, resolvePostLoginPath } from '@/lib/routes'

describe('product routes (Wave S)', () => {
  it('maps legacy panels to product paths', () => {
    expect(PANEL_REDIRECTS['/panels/chat']).toBe('/workspace/chat')
    expect(PANEL_REDIRECTS['/panels/admin']).toBe('/governance/keys')
    expect(PANEL_REDIRECTS['/panels/rag']).toBe('/knowledge')
  })

  it('resolvePostLoginPath prefers next and remaps legacy', () => {
    expect(resolvePostLoginPath(null)).toBe(HOME_PATH)
    expect(resolvePostLoginPath('/panels/chat')).toBe('/workspace/chat')
    expect(resolvePostLoginPath('/governance/org')).toBe('/governance/org')
  })
})
