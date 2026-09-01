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

describe('HomeChat image path (76b)', () => {
  it('uses session upload, not legacy multimodal chat', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    const src = readFileSync(join(process.cwd(), 'src/pages/agent/HomeChat.tsx'), 'utf8')
    expect(src).not.toMatch(/postMultimodalChat/)
    expect(src).not.toMatch(/canVision/)
    expect(src).not.toMatch(/multimodal:vision/)
    expect(src).not.toMatch(/attachment_ids/)
    expect(src).toMatch(/uploadSessionFile/)
    expect(src).toMatch(/image\/webp/)
    expect(src).toMatch(/上传并识别中/)
  })
})
