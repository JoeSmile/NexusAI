import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { DislikeReasonDialog } from '@/components/agent/DislikeReasonDialog'

describe('DislikeReasonDialog', () => {
  it('keeps submit disabled until a reason or note is filled', async () => {
    const onSubmit = vi.fn()
    render(
      <DislikeReasonDialog open onOpenChange={() => undefined} onSubmit={onSubmit} />,
    )
    const submit = screen.getByRole('button', { name: '提交差评' })
    expect((submit as HTMLButtonElement).disabled).toBe(true)
    await userEvent.click(screen.getByRole('button', { name: '答非所问' }))
    expect((submit as HTMLButtonElement).disabled).toBe(false)
    await userEvent.click(submit)
    expect(onSubmit).toHaveBeenCalledWith(['off_topic'], '')
  })
})
