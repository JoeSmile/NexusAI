/**
 * Task 94 S3 — poll v2（snapshot status 分流 / 终态文本回填 / 404 降级 / 长轮询上限）。
 */
import { ApiError } from '@/api/http'
import { pollRunSnapshot } from '@/hooks/streamReconnect'
import { afterEach, describe, expect, it, vi } from 'vitest'

const { fetchRunSnapshotMock, lookupMock } = vi.hoisted(() => ({
  fetchRunSnapshotMock: vi.fn(),
  lookupMock: vi.fn(),
}))

vi.mock('@/api/chat', () => ({
  fetchRunSnapshot: fetchRunSnapshotMock,
  fetchAssistantMessageByClientId: lookupMock,
}))

const SNAP = (over: Record<string, unknown> = {}) => ({
  trace_id: 'tr-1',
  status: 'completed',
  snapshot: { goal: '', nodes: [] },
  events: [],
  latest_seq: 0,
  ...over,
})

async function run(fn: () => Promise<unknown>): Promise<unknown> {
  // poll 节奏 [1000, 2000, 3000...]；用假时钟快进
  vi.useFakeTimers()
  const p = fn()
  await vi.advanceTimersByTimeAsync(30_000)
  return p
}

afterEach(() => {
  vi.useRealTimers()
  fetchRunSnapshotMock.mockReset()
  lookupMock.mockReset()
})

describe('pollRunSnapshot poll v2 (Task 94 S3)', () => {
  it('completed → complete，并按 assistant cid 回拉终态文本', async () => {
    fetchRunSnapshotMock.mockResolvedValue(SNAP({ status: 'completed' }))
    lookupMock.mockResolvedValue({
      found: true,
      message: {
        id: 7,
        role: 'assistant',
        content: 'FULL TEXT',
        client_message_id: 'c1',
      },
    })
    const out = (await run(() =>
      pollRunSnapshot({ traceId: 'tr-1', assistantClientMessageId: 'c1' }),
    )) as Awaited<ReturnType<typeof pollRunSnapshot>>
    expect(out.result).toBe('complete')
    expect(out.finalContent).toBe('FULL TEXT')
    expect(lookupMock).toHaveBeenCalledWith('c1')
  })

  it('streaming → 续轮询，直至 completed（不再 5 次就 timeout）', async () => {
    fetchRunSnapshotMock
      .mockResolvedValueOnce(SNAP({ status: 'streaming' }))
      .mockResolvedValueOnce(SNAP({ status: 'streaming' }))
      .mockResolvedValueOnce(SNAP({ status: 'completed' }))
    lookupMock.mockResolvedValue({ found: false })
    const out = (await run(() =>
      pollRunSnapshot({ traceId: 'tr-1', assistantClientMessageId: 'c1' }),
    )) as Awaited<ReturnType<typeof pollRunSnapshot>>
    expect(fetchRunSnapshotMock).toHaveBeenCalledTimes(3)
    expect(out.result).toBe('complete')
    expect(out.finalContent).toBeUndefined()
  })

  it('cancelled / failed → 对应终态', async () => {
    fetchRunSnapshotMock.mockResolvedValue(SNAP({ status: 'cancelled' }))
    const c = (await run(() => pollRunSnapshot({ traceId: 'tr-1' }))) as Awaited<
      ReturnType<typeof pollRunSnapshot>
    >
    expect(c.result).toBe('cancelled')

    fetchRunSnapshotMock.mockReset()
    fetchRunSnapshotMock.mockResolvedValue(SNAP({ status: 'failed' }))
    const f = (await run(() => pollRunSnapshot({ traceId: 'tr-1' }))) as Awaited<
      ReturnType<typeof pollRunSnapshot>
    >
    expect(f.result).toBe('failed')
  })

  it('404（终态窗已过）→ 按 cid 降级查 DB；查到=complete', async () => {
    fetchRunSnapshotMock.mockRejectedValue(
      new ApiError({ status: 404, code: 'run_not_found', message: 'run_not_found' }),
    )
    lookupMock.mockResolvedValue({
      found: true,
      message: { id: 9, role: 'assistant', content: 'DB TEXT', client_message_id: 'c2' },
    })
    const out = (await run(() =>
      pollRunSnapshot({ traceId: 'tr-x', assistantClientMessageId: 'c2' }),
    )) as Awaited<ReturnType<typeof pollRunSnapshot>>
    expect(out.result).toBe('complete')
    expect(out.finalContent).toBe('DB TEXT')
  })

  it('404 且 DB 无记录 → not_found', async () => {
    fetchRunSnapshotMock.mockRejectedValue(
      new ApiError({ status: 404, code: 'run_not_found', message: 'run_not_found' }),
    )
    lookupMock.mockResolvedValue({ found: false })
    const out = (await run(() =>
      pollRunSnapshot({ traceId: 'tr-x', assistantClientMessageId: 'c3' }),
    )) as Awaited<ReturnType<typeof pollRunSnapshot>>
    expect(out.result).toBe('not_found')
  })

  it('恢复期瞬时 5xx 不放弃，按节奏重试至终态', async () => {
    fetchRunSnapshotMock
      .mockRejectedValueOnce(new ApiError({ status: 502, code: 'bad_gateway', message: '502' }))
      .mockResolvedValueOnce(SNAP({ status: 'completed' }))
    lookupMock.mockResolvedValue({ found: false })
    const out = (await run(() => pollRunSnapshot({ traceId: 'tr-1' }))) as Awaited<
      ReturnType<typeof pollRunSnapshot>
    >
    expect(out.result).toBe('complete')
    expect(fetchRunSnapshotMock).toHaveBeenCalledTimes(2)
  })

  it('超过 maxWaitMs（逼近 TTL）→ timeout 兜底', async () => {
    vi.useFakeTimers()
    fetchRunSnapshotMock.mockResolvedValue(SNAP({ status: 'streaming' }))
    const p = pollRunSnapshot({ traceId: 'tr-1', maxWaitMs: 1500 })
    await vi.advanceTimersByTimeAsync(10_000)
    const out = (await p) as Awaited<ReturnType<typeof pollRunSnapshot>>
    expect(out.result).toBe('timeout')
    expect(fetchRunSnapshotMock).toHaveBeenCalledTimes(1) // 第一次 1s 内跑，第二次已超窗不再请求
  })

  it('signal 中止 → timeout 返回且不再请求', async () => {
    vi.useFakeTimers()
    const ac = new AbortController()
    fetchRunSnapshotMock.mockResolvedValue(SNAP({ status: 'streaming' }))
    const p = pollRunSnapshot({ traceId: 'tr-1', signal: ac.signal })
    ac.abort()
    await vi.advanceTimersByTimeAsync(5_000)
    const out = (await p) as Awaited<ReturnType<typeof pollRunSnapshot>>
    expect(out.result).toBe('timeout')
    expect(fetchRunSnapshotMock).not.toHaveBeenCalled()
  })
})
