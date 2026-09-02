import { beforeEach, describe, expect, it, vi } from 'vitest'

import { generateTopicBrief, setArtifactVisibility } from '@/api/contentOps'

const { apiPostMock } = vi.hoisted(() => ({
  apiPostMock: vi.fn(),
}))

vi.mock('@/api/http', () => ({
  apiPost: apiPostMock,
  apiGet: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}))

beforeEach(() => {
  apiPostMock.mockReset()
  apiPostMock.mockResolvedValue({
    id: 'a1',
    kind: 'script',
    title: '稿',
    body: {},
    visibility: 'shared',
    is_owner: true,
  })
})

describe('setArtifactVisibility (45b.4)', () => {
  it('POSTs tenant share toggle', async () => {
    await setArtifactVisibility('a1', 'shared')
    expect(apiPostMock).toHaveBeenCalledWith(
      '/api/content/artifacts/a1/visibility',
      { visibility: 'shared' },
    )
  })
})

describe('generateTopicBrief (45b.5)', () => {
  it('POSTs /api/content/topics/brief', async () => {
    apiPostMock.mockResolvedValueOnce({ kind: 'brief', title: '专升本报名', key_points: [] })
    await generateTopicBrief({ title: '专升本报名', summary: '窗口将至' })
    expect(apiPostMock).toHaveBeenCalledWith('/api/content/topics/brief', {
      title: '专升本报名',
      summary: '窗口将至',
    })
  })
})
