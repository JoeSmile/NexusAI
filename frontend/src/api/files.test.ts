import { beforeEach, describe, expect, it, vi } from 'vitest'

import { uploadSessionFile } from '@/api/files'

const { apiPostMock } = vi.hoisted(() => ({
  apiPostMock: vi.fn(),
}))

vi.mock('@/api/http', () => ({
  apiPost: apiPostMock,
}))

beforeEach(() => {
  apiPostMock.mockReset()
  apiPostMock.mockResolvedValue({
    attachment_id: 'att-1',
    status: 'ready',
    describe_status: 'ready',
  })
})

describe('uploadSessionFile (76b)', () => {
  it('POSTs /api/files with file + session_id FormData', async () => {
    const file = new File(['png'], 'shot.png', { type: 'image/png' })
    await uploadSessionFile(file, 'workspace-chat')
    expect(apiPostMock).toHaveBeenCalledTimes(1)
    const [path, body] = apiPostMock.mock.calls[0]
    expect(path).toBe('/api/files')
    expect(body).toBeInstanceOf(FormData)
    const form = body as FormData
    expect(form.get('file')).toBe(file)
    expect(form.get('session_id')).toBe('workspace-chat')
  })
})
