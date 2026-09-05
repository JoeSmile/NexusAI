import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const loginWithPassword = vi.fn()
const acceptTerms = vi.fn()
const fetchTermsCurrent = vi.fn()

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (sel: (s: { loginWithPassword: typeof loginWithPassword }) => unknown) =>
    sel({ loginWithPassword }),
}))

vi.mock('@/api/terms', () => ({
  USER_AGREEMENT_KIND: 'user_agreement',
  fetchTermsCurrent: (...args: unknown[]) => fetchTermsCurrent(...args),
  acceptTerms: (...args: unknown[]) => acceptTerms(...args),
}))

import AgentLoginPage from '@/pages/agent/LoginPage'

describe('AgentLoginPage terms checkbox', () => {
  beforeEach(() => {
    loginWithPassword.mockReset()
    acceptTerms.mockReset()
    fetchTermsCurrent.mockReset()
    fetchTermsCurrent.mockResolvedValue({
      id: 1,
      kind: 'user_agreement',
      version: 'v1.0.0',
      content_md: '# 用户协议',
    })
    loginWithPassword.mockResolvedValue(undefined)
    acceptTerms.mockResolvedValue({ kind: 'user_agreement', version: 'v1.0.0' })
  })

  it('blocks login until the agreement checkbox is checked, then records accept', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <AgentLoginPage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('checkbox', { name: /用户协议/ })).toBeTruthy()
    await waitFor(() => expect(fetchTermsCurrent).toHaveBeenCalled())
    const submit = screen.getByRole('button', { name: '登录' })
    expect(submit).toBeDisabled()

    await user.type(screen.getByLabelText('密码'), 'secret')
    expect(submit).toBeDisabled()

    await user.click(screen.getByRole('checkbox', { name: /用户协议/ }))
    expect(submit).not.toBeDisabled()

    await user.click(submit)
    await waitFor(() => expect(loginWithPassword).toHaveBeenCalled())
    expect(acceptTerms).toHaveBeenCalledWith('user_agreement', 'v1.0.0')
  })
})
