import { describe, expect, it } from 'vitest'

import { cleanBotResponseForFeedback } from '@/api/feedback'

describe('cleanBotResponseForFeedback', () => {
  it('strips dig markers and 查看明细', () => {
    const raw =
      '✅ 已抓取 2 条\n\n[查看明细]\n\n<<<DIG>>>\n1. a\n<<<END>>>'
    expect(cleanBotResponseForFeedback(raw)).toBe('✅ 已抓取 2 条')
  })

  it('leaves plain text', () => {
    expect(cleanBotResponseForFeedback('hello')).toBe('hello')
  })
})

  it('keeps script body for copy/bookmark', () => {
    const raw = '✅ 口播稿已生成。\n\n<<<SCRIPT>>>\n大家好\n<<<END>>>'
    expect(cleanBotResponseForFeedback(raw)).toBe('大家好')
  })

