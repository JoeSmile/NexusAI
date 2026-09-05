import { beforeEach, describe, expect, it, vi } from 'vitest'

import { generateTopicBrief, setArtifactVisibility, deleteArtifact } from '@/api/contentOps'

const { apiPostMock, apiDeleteMock } = vi.hoisted(() => ({
  apiPostMock: vi.fn(),
  apiDeleteMock: vi.fn(),
}))

vi.mock('@/api/http', () => ({
  apiPost: apiPostMock,
  apiGet: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: apiDeleteMock,
}))

beforeEach(() => {
  apiPostMock.mockReset()
  apiDeleteMock.mockReset()
  apiPostMock.mockResolvedValue({
    id: 'a1',
    kind: 'script',
    title: '稿',
    body: {},
    visibility: 'shared',
    is_owner: true,
  })
  apiDeleteMock.mockResolvedValue({
    deleted: true,
    id: 'a1',
    kind: 'script',
    title: '稿',
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

describe('deleteArtifact (84-sec S5)', () => {
  it('DELETEs artifact by id', async () => {
    await deleteArtifact('a1', 'script')
    expect(apiDeleteMock).toHaveBeenCalledWith('/api/content/artifacts/a1?kind=script')
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
