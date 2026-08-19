/**
 * Bookmarks drawer — separate from ContextPanel (config).
 * Lists POST bookmark snapshots via GET /feedback/mine?type=bookmark.
 */
import { useCallback, useEffect, useState } from 'react'
import { Bookmark } from 'lucide-react'
import { toast } from 'sonner'

import {
  deleteMyFeedback,
  listMyFeedback,
  type FeedbackMineItem,
} from '@/api/feedback'
import { formatApiError } from '@/api/http'
import { WORKSPACE_CHAT_SESSION } from '@/api/chat'
import { RightDrawer } from '@/components/agent/RightDrawer'

function previewText(item: FeedbackMineItem, max = 120): string {
  const raw = (item.bot_response || item.comment || '').trim()
  if (!raw) return '（无正文快照）'
  return raw.length > max ? `${raw.slice(0, max)}…` : raw
}

export function BookmarksDrawer({
  open,
  onClose,
  onChanged,
}: {
  open: boolean
  onClose: () => void
  /** Notify chat to re-hydrate star state after unstar */
  onChanged?: () => void
}) {
  const [items, setItems] = useState<FeedbackMineItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})
  const [busyId, setBusyId] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await listMyFeedback({
        type: 'bookmark',
        session_id: WORKSPACE_CHAT_SESSION,
        limit: 50,
      })
      setItems(res.items ?? [])
      setTotal(res.total ?? res.items?.length ?? 0)
    } catch (e) {
      setError(formatApiError(e, '加载收藏失败'))
      setItems([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    void load()
  }, [open, load])

  const unstar = async (id: number) => {
    if (busyId != null) return
    setBusyId(id)
    try {
      await deleteMyFeedback(id)
      setItems((list) => list.filter((x) => x.id !== id))
      setTotal((t) => Math.max(0, t - 1))
      toast.success('已取消收藏')
      onChanged?.()
    } catch (e) {
      toast.error(formatApiError(e, '取消失败'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <RightDrawer open={open} title="我的收藏" onClose={onClose}>
      {loading ? (
        <p className="bookmarks-hint">加载中…</p>
      ) : error ? (
        <div className="bookmarks-hint">
          <p style={{ color: 'var(--color-danger, #dc2626)' }}>{error}</p>
          <button type="button" className="btn-secondary btn-sm" onClick={() => void load()}>
            重试
          </button>
        </div>
      ) : items.length === 0 ? (
        <p className="bookmarks-hint">
          暂无收藏。在 AI 回复下方点星标即可收藏到这里。
        </p>
      ) : (
        <>
          <p className="bookmarks-meta">共 {total} 条（最多显示 50）</p>
          <ul className="bookmarks-list">
            {items.map((it) => {
              const openItem = !!expanded[it.id]
              const full = (it.bot_response || '').trim()
              return (
                <li key={it.id} className="bookmarks-item">
                  <div className="bookmarks-item-head">
                    <Bookmark
                      size={14}
                      strokeWidth={1.75}
                      fill="currentColor"
                      className="bookmarks-item-icon"
                    />
                    <span className="bookmarks-item-time">
                      {it.created_at
                        ? new Date(it.created_at).toLocaleString()
                        : '—'}
                    </span>
                    <button
                      type="button"
                      className="bookmarks-item-unstar"
                      disabled={busyId === it.id}
                      onClick={() => void unstar(it.id)}
                    >
                      取消
                    </button>
                  </div>
                  {it.user_message ? (
                    <div className="bookmarks-q">问：{it.user_message}</div>
                  ) : null}
                  <div className="bookmarks-a">
                    {openItem ? full || '（无正文快照）' : previewText(it)}
                  </div>
                  {full.length > 120 ? (
                    <button
                      type="button"
                      className="bookmarks-expand"
                      onClick={() =>
                        setExpanded((s) => ({ ...s, [it.id]: !s[it.id] }))
                      }
                    >
                      {openItem ? '收起' : '展开全文'}
                    </button>
                  ) : null}
                </li>
              )
            })}
          </ul>
        </>
      )}
    </RightDrawer>
  )
}
