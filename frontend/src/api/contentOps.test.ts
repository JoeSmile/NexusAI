import { beforeEach, describe, expect, it, vi } from 'vitest'

import { setArtifactVisibility } from '@/api/contentOps'

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
