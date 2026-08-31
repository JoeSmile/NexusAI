import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CacheAnswerBadge } from '@/components/agent/CacheAnswerBadge'

describe('CacheAnswerBadge (Task 80.2)', () => {
  it('shows 缓存回答 with exact tooltip', () => {
    render(<CacheAnswerBadge cacheType="exact" />)
    const badge = screen.getByText('缓存回答')
    expect(badge).toBeTruthy()
    expect(badge.getAttribute('title')).toBe('exact')
  })

  it('shows 模板 tooltip for template hits', () => {
    render(<CacheAnswerBadge cacheType="template" />)
    expect(screen.getByText('缓存回答').getAttribute('title')).toBe('模板')
  })
})
