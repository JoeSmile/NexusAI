import { describe, expect, it } from 'vitest'

import {
  canConfigureTenantLlm,
  pickDefaultModelId,
} from '@/lib/chatModels'

describe('chatModels', () => {
  it('pickDefaultModelId prefers single tenant model', () => {
    const items = [{ model: 'qwen2.5:7b', series: 'chat', configured: true }]
    expect(pickDefaultModelId(items, '')).toBe('qwen2.5:7b')
    expect(pickDefaultModelId(items, 'stale')).toBe('qwen2.5:7b')
  })

  it('pickDefaultModelId keeps valid current when multiple models', () => {
    const items = [
      { model: 'a', series: 'chat', configured: true },
      { model: 'b', series: 'chat', configured: true },
    ]
    expect(pickDefaultModelId(items, 'b')).toBe('b')
    expect(pickDefaultModelId(items, 'missing')).toBe('a')
  })

  it('canConfigureTenantLlm is admin roles only', () => {
    expect(canConfigureTenantLlm('tenant_admin')).toBe(true)
    expect(canConfigureTenantLlm('super_admin')).toBe(true)
    expect(canConfigureTenantLlm('user')).toBe(false)
    expect(canConfigureTenantLlm('auditor')).toBe(false)
  })
})
