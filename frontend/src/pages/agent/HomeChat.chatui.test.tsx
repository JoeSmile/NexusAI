/**
 * Regression: @chatui/core must share app React (no CJS deep-import MessageContainer).
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Bubble, Message, PullToRefresh } from '@chatui/core'

describe('chatui Message (single React)', () => {
  it('PullToRefresh root import shares React (single child)', () => {
    const { container } = render(
      <PullToRefresh onRefresh={async () => undefined} loadMoreText="加载更早的消息…">
        <div>
          <span>ptr-child</span>
        </div>
      </PullToRefresh>,
    )
    expect(container.textContent).toContain('ptr-child')
  })

  it('renders without useState null crash', () => {
    render(
      <Message
        _id="m1"
        type="text"
        position="left"
        content={{ text: 'hello' }}
        renderMessageContent={(msg) => (
          <Bubble>
            <span>{String(msg.content?.text ?? '')}</span>
          </Bubble>
        )}
      />,
    )
    expect(screen.getByText('hello')).toBeTruthy()
  })
})
