import { describe, expect, it } from 'vitest'

import { EMBEDDING_DIMENSIONS, maskApiKeyPreview } from './llm'

describe('llm helpers', () => {
  it('maskApiKeyPreview keeps first/last 6 with ***', () => {
    expect(maskApiKeyPreview('sk-abcdefghijklmnopqr')).toBe('sk-abc***mnopqr')
    const long = 'ABCDEFGHIJKLMNOPQRSTUV'
    expect(maskApiKeyPreview(long)).toBe('ABCDEF***QRSTUV')
  })

  it('maskApiKeyPreview supports edge=8', () => {
    expect(maskApiKeyPreview('ABCDEFGHIJKLMNOPQRSTUVWX', 8)).toBe('ABCDEFGH***QRSTUVWX')
  })

  it('maskApiKeyPreview short keys still mask', () => {
    expect(maskApiKeyPreview('short')).toBe('s***t')
  })

  it('embedding dimensions constant', () => {
    expect(EMBEDDING_DIMENSIONS).toBe(1536)
  })
})
