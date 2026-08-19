import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/api/social', () => ({
  probeSocialAccount: vi.fn(),
  startSocialAnalysis: vi.fn(),
  getSocialTask: vi.fn(),
  retrySocialTask: vi.fn(),
  listSocialContents: vi.fn(),
  listSocialFollows: vi.fn().mockResolvedValue({ items: [] }),
  exportSocialXlsx: vi.fn(),
  replicaSocialBatch: vi.fn(),
}))

import SocialBenchmarkPage from '@/pages/content/SocialBenchmark'

describe('SocialBenchmarkPage', () => {
  it('renders probe form', () => {
    render(
      <MemoryRouter>
        <SocialBenchmarkPage />
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { name: '社媒对标' })).toBeTruthy()
    expect(screen.getByText('添加关注')).toBeTruthy()
    expect(screen.getByText('拉取内容')).toBeTruthy()
    expect(screen.getByText('结构分析')).toBeTruthy()
    expect(screen.getByText('关注的 UP 主')).toBeTruthy()
  })
})
