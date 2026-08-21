/**
 * 47b slice2 — read-only history timeline + keyword search.
 * Does not inject into the live chat list (single-session, browse only).
 */
import { useCallback, useEffect, useState } from 'react'
import { History } from 'lucide-react'

import {
  WORKSPACE_CHAT_SESSION,
  fetchChatTimeline,
  searchChatHistory,
  type ChatHistoryItem,
  type ChatTimelineGroup,
} from '@/api/chat'
import { formatApiError } from '@/api/http'
import { RightDrawer } from '@/components/agent/RightDrawer'

function mergeTimelineGroups(
  newer: ChatTimelineGroup[],
  older: ChatTimelineGroup[],
): ChatTimelineGroup[] {
  const map = new Map<string, ChatTimelineGroup>()
  const order: string[] = []
  for (const g of newer) {
    map.set(g.date, { ...g, items: [...g.items] })
    order.push(g.date)
  }
  for (const g of older) {
    const existing = map.get(g.date)
    if (existing) {
      existing.items = [...g.items, ...existing.items]
      existing.count = existing.items.length
      existing.preview = existing.items[0]?.content || existing.preview
    } else {
      map.set(g.date, { ...g, items: [...g.items] })
      order.push(g.date)
    }
  }
  return order.map((d) => map.get(d)!)
}

function oldestId(groups: ChatTimelineGroup[]): number | undefined {
  let min: number | undefined
  for (const g of groups) {
    for (const it of g.items) {
      if (min == null || it.id < min) min = it.id
    }
  }
  return min
}

function preview(text: string, max = 72): string {
  const t = text.trim()
  if (!t) return '（空）'
  return t.length > max ? `${t.slice(0, max)}…` : t
}

export function HistoryDrawer({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [groups, setGroups] = useState<ChatTimelineGroup[]>([])
  const [hint, setHint] = useState('还没有历史对话。发一条消息后，可在这里按天回看。')
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [error, setError] = useState('')
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<ChatHistoryItem[] | null>(null)
  const [openDay, setOpenDay] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetchChatTimeline(WORKSPACE_CHAT_SESSION, { limit: 50 })
      setGroups(res.groups ?? [])
      setHasMore(Boolean(res.has_more))
      if (res.empty_hint) setHint(res.empty_hint)
    } catch (e) {
      setError(formatApiError(e, '加载历史失败'))
      setGroups([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    setHits(null)
    setQ('')
    setOpenDay(null)
    setHasMore(false)
    void load()
  }, [open, load])

  const onSearch = async () => {
    const needle = q.trim()
    if (!needle) {
      setHits(null)
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await searchChatHistory(WORKSPACE_CHAT_SESSION, needle)
      setHits(res.items ?? [])
    } catch (e) {
      setError(formatApiError(e, '搜索失败'))
      setHits([])
    } finally {
      setLoading(false)
    }
  }

  const loadMore = async () => {
    const cursor = oldestId(groups)
    if (!hasMore || cursor == null || loadingMore) return
    setLoadingMore(true)
    setError('')
    try {
      const res = await fetchChatTimeline(WORKSPACE_CHAT_SESSION, {
        limit: 50,
        beforeId: cursor,
      })
      setGroups((cur) => mergeTimelineGroups(cur, res.groups ?? []))
      setHasMore(Boolean(res.has_more))
    } catch (e) {
      setError(formatApiError(e, '加载更早失败'))
    } finally {
      setLoadingMore(false)
    }
  }

  return (
    <RightDrawer open={open} title="对话历史" onClose={onClose}>
      <form
        className="history-search"
        onSubmit={(e) => {
          e.preventDefault()
          void onSearch()
        }}
      >
        <input
          className="history-search-input"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜索历史对话…"
          aria-label="搜索历史对话"
        />
        <button type="submit" className="btn-secondary btn-sm">
          搜索
        </button>
        {hits != null ? (
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={() => {
              setHits(null)
              setQ('')
            }}
          >
            清除
          </button>
        ) : null}
      </form>
      {loading ? (
        <p className="bookmarks-hint">加载中…</p>
      ) : error ? (
        <div className="bookmarks-hint">
          <p style={{ color: 'var(--color-danger, #dc2626)' }}>{error}</p>
          <button type="button" className="btn-secondary btn-sm" onClick={() => void load()}>
            重试
          </button>
        </div>
      ) : hits != null ? (
        hits.length === 0 ? (
          <p className="bookmarks-hint">没有匹配的历史片段</p>
        ) : (
          <ul className="bookmarks-list">
            {hits.map((it) => (
              <li key={it.id} className="bookmarks-item">
                <div className="bookmarks-item-head">
                  <History size={14} className="bookmarks-item-icon" />
                  <span className="bookmarks-item-time">
                    {it.created_at ? new Date(it.created_at).toLocaleString() : '—'}
                  </span>
                </div>
                <div className="bookmarks-q">
                  {it.role === 'user' ? '问' : '答'}：{preview(it.content, 200)}
                </div>
              </li>
            ))}
          </ul>
        )
      ) : groups.length === 0 ? (
        <p className="bookmarks-hint">{hint}</p>
      ) : (
        <ul className="bookmarks-list">
          {groups.map((g) => {
            const expanded = openDay === g.date
            return (
              <li key={g.date} className="bookmarks-item">
                <button
                  type="button"
                  className="history-day-btn"
                  onClick={() => setOpenDay(expanded ? null : g.date)}
                >
                  <span className="history-day-date">{g.date}</span>
                  <span className="history-day-meta">
                    {g.count} 条 · {preview(g.preview)}
                  </span>
                </button>
                {expanded
                  ? g.items.map((it) => (
                      <div key={it.id} className="history-day-msg">
                        <span className="history-day-role">
                          {it.role === 'user' ? '你' : 'N'}
                        </span>
                        {it.content}
                      </div>
                    ))
                  : null}
              </li>
            )
          })}
        </ul>
      )}
      {!loading && hits == null && hasMore ? (
        <button
          type="button"
          className="btn-secondary btn-sm"
          style={{ marginTop: 8 }}
          disabled={loadingMore}
          onClick={() => void loadMore()}
        >
          {loadingMore ? '加载中…' : '加载更早'}
        </button>
      ) : null}
    </RightDrawer>
  )
}
