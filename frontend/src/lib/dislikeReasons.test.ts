import { describe, expect, it } from 'vitest'

import {
  DISLIKE_REASONS,
  formatDislikeComment,
} from '@/lib/dislikeReasons'

describe('formatDislikeComment', () => {
  it('has six provisional reasons', () => {
    expect(DISLIKE_REASONS).toHaveLength(6)
  })

  it('joins selected labels and optional note', () => {
    expect(formatDislikeComment(['off_topic', 'too_long'], '  偏题  ')).toBe(
      '答非所问；太长太啰嗦 | 补充：偏题',
    )
  })

  it('returns empty when nothing selected', () => {
    expect(formatDislikeComment([], '   ')).toBe('')
  })
})
