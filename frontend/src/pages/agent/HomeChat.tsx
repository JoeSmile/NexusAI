/**
 * Homepage chat — @chatui/core Message/Bubble + AgentUI input + /chat/streaming.
 * 47b slice0: history load + client_message_id + cursor pagination;
 * 45b dig in-place.
 *
 * Do NOT deep-import `@chatui/core/lib/...` (CJS) — Vite serves a second React
 * and hooks explode with "Cannot read properties of null (reading 'useState')".
 */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type UIEvent } from 'react'
import { Bubble, Message, PullToRefresh, type MessageProps } from '@chatui/core'
import { Bookmark, Copy, ThumbsDown, ThumbsUp } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import '@chatui/core/dist/index.css'

import {
  CHAT_STREAM_ENDPOINT,
  WORKSPACE_CHAT_SESSION,
  fetchChatHistory,
  postChatNote,
} from '@/api/chat'
import { formatApiError } from '@/api/http'
import { ContextPanel } from '@/components/agent/ContextPanel'
import { BookmarksDrawer } from '@/components/agent/BookmarksDrawer'
import { DislikeReasonDialog } from '@/components/agent/DislikeReasonDialog'
import { HistoryDrawer } from '@/components/agent/HistoryDrawer'
import { HotspotDayCollectionDialog } from '@/components/agent/HotspotDayCollectionDialog'
import {
  HotspotDigDialog,
  type HotspotDigFormValues,
} from '@/components/agent/HotspotDigDialog'
import {
  ScriptGenDialog,
  type ScriptGenFormValues,
} from '@/components/agent/ScriptGenDialog'
import { useBubbleFeedback } from '@/hooks/useBubbleFeedback'
import { useChatStream, type ChatMessage } from '@/hooks/useChatStream'
import { runHotspotDigInPlace } from '@/lib/runHotspotDigInPlace'
import { runScriptGenInPlace } from '@/lib/runScriptGenInPlace'
import { useChatPrefsStore } from '@/stores/chatPrefsStore'
import { useWorkflowTriggerStore } from '@/stores/workflowTriggerStore'

export default function HomeChatPage() {
  const {
    messages,
    streaming,
    hasMore,
    send,
    abort,
    appendLocal,
    patchLocal,
    replaceHistory,
    prependHistory,
  } = useChatStream(CHAT_STREAM_ENDPOINT)
  const {
    byMsg: feedbackByMsg,
    hydrate: hydrateFeedback,
    copyText,
    toggleReaction,
    submitDislike,
    toggleBookmark,
    busy: feedbackBusy,
  } = useBubbleFeedback()
  const [input, setInput] = useState('')
  const [digOpen, setDigOpen] = useState(false)
  const [digBusy, setDigBusy] = useState(false)
  const [scriptOpen, setScriptOpen] = useState(false)
  const [scriptBusy, setScriptBusy] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [expandedDig, setExpandedDig] = useState<Record<string, boolean>>({})
  const [wfToast, setWfToast] = useState<string | null>(null)
  const [bookmarksOpen, setBookmarksOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [dayCollectionOpen, setDayCollectionOpen] = useState(false)
  const [dislikeCid, setDislikeCid] = useState<string | null>(null)
  /** 历史首屏加载完成后强制滚底（内容运营切回对话） */
  const [historyScrollNonce, setHistoryScrollNonce] = useState(0)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const digAbortRef = useRef<AbortController | null>(null)
  /** dig 轮询与 chat SSE 分离：abort chat 不得取消 dig */
  const digRunningRef = useRef(false)
  const scriptRunningRef = useRef(false)
  const loadingMoreRef = useRef(false)
  /** prepend 时禁止 stick-to-bottom，避免加载更早后被拽回底部 */
  const skipStickBottomRef = useRef(false)
  const stickBottomRef = useRef(true)
  const ptrRef = useRef<{
    wrapperRef: React.RefObject<HTMLDivElement | null>
  } | null>(null)
  const HISTORY_PAGE = 10

  const mapHistoryItems = useCallback(
    (items: Awaited<ReturnType<typeof fetchChatHistory>>['items']): ChatMessage[] =>
      items.map((it) => ({
        id: it.client_message_id || `hist-${it.id}`,
        role: (it.role === 'user' ? 'user' : 'assistant') as ChatMessage['role'],
        content: it.content,
        status: 'done' as const,
        dbId: it.id,
      })),
    [],
  )

  const modelId = useChatPrefsStore((s) => s.modelId)
  const temperature = useChatPrefsStore((s) => s.temperature)
  const maxTokens = useChatPrefsStore((s) => s.maxTokens)
  const contextOpen = useChatPrefsStore((s) => s.contextOpen)
  const setContextOpen = useChatPrefsStore((s) => s.setContextOpen)
  const triggerKind = useWorkflowTriggerStore((s) => s.kind)
  const triggerNonce = useWorkflowTriggerStore((s) => s.nonce)
  const clearTrigger = useWorkflowTriggerStore((s) => s.clear)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await fetchChatHistory(WORKSPACE_CHAT_SESSION, HISTORY_PAGE)
        if (cancelled) return
        replaceHistory(mapHistoryItems(res.items), !!res.has_more)
        stickBottomRef.current = true
        void hydrateFeedback(WORKSPACE_CHAT_SESSION)
        setHistoryError(null)
        setHistoryScrollNonce((n) => n + 1)
      } catch (e) {
        if (!cancelled) setHistoryError(formatApiError(e))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [replaceHistory, mapHistoryItems, hydrateFeedback])

  // 历史渲染进 PullToRefresh 后再滚底（单次 rAF 常赶不上 commit）
  // 仅跟 historyScrollNonce：勿依赖 messages.length，否则「加载更早」会误滚底
  useEffect(() => {
    if (!historyScrollNonce) return
    stickBottomRef.current = true
    const scrollBottom = () => {
      endRef.current?.scrollIntoView({ behavior: 'auto', block: 'end' })
      const el = ptrRef.current?.wrapperRef?.current
      if (el) el.scrollTop = el.scrollHeight
    }
    scrollBottom()
    const raf = requestAnimationFrame(() => {
      scrollBottom()
      requestAnimationFrame(scrollBottom)
    })
    const t1 = window.setTimeout(scrollBottom, 80)
    const t2 = window.setTimeout(scrollBottom, 250)
    return () => {
      cancelAnimationFrame(raf)
      window.clearTimeout(t1)
      window.clearTimeout(t2)
    }
  }, [historyScrollNonce])

  const onLoadOlder = useCallback(async () => {
    if (!hasMore || loadingMoreRef.current) return
    const earliest = messages.reduce<number | undefined>((min, m) => {
      if (m.dbId == null) return min
      return min == null ? m.dbId : Math.min(min, m.dbId)
    }, undefined)
    if (earliest == null) return
    loadingMoreRef.current = true
    const scroller = ptrRef.current?.wrapperRef?.current ?? null
    const prevHeight = scroller?.scrollHeight ?? 0
    const prevTop = scroller?.scrollTop ?? 0
    skipStickBottomRef.current = true
    try {
      const res = await fetchChatHistory(
        WORKSPACE_CHAT_SESSION,
        HISTORY_PAGE,
        earliest,
      )
      prependHistory(mapHistoryItems(res.items), !!res.has_more)
      void hydrateFeedback(WORKSPACE_CHAT_SESSION)
      setHistoryError(null)
      // 保持视口：prepend 后补偿 scrollHeight 增量
      requestAnimationFrame(() => {
        const el = ptrRef.current?.wrapperRef?.current
        if (el && prevHeight > 0) {
          el.scrollTop = el.scrollHeight - prevHeight + prevTop
        }
        skipStickBottomRef.current = false
      })
    } catch (e) {
      skipStickBottomRef.current = false
      setHistoryError(formatApiError(e))
    } finally {
      loadingMoreRef.current = false
    }
  }, [
    hasMore,
    messages,
    prependHistory,
    mapHistoryItems,
    hydrateFeedback,
  ])

  const onMessagesScroll = useCallback(
    (e: UIEvent<HTMLDivElement>) => {
      const el = e.currentTarget
      const distBottom = el.scrollHeight - el.scrollTop - el.clientHeight
      stickBottomRef.current = distBottom < 96
      // 滚到顶部附近自动加载更早（桌面无触控下拉时也生效）
      if (el.scrollTop <= 56 && hasMore && !loadingMoreRef.current) {
        void onLoadOlder()
      }
    },
    [hasMore, onLoadOlder],
  )

  useEffect(() => {
    if (skipStickBottomRef.current) return
    if (!stickBottomRef.current && !streaming) return
    endRef.current?.scrollIntoView({ behavior: streaming ? 'auto' : 'smooth' })
  }, [messages, streaming])

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [input])

  const startHotspotDig = (form: HotspotDigFormValues) => {
    if (digRunningRef.current) {
      appendLocal('assistant', '已有抓取任务进行中，请稍候…')
      return
    }
    digRunningRef.current = true
    setDigBusy(true)
    digAbortRef.current?.abort()
    const ac = new AbortController()
    digAbortRef.current = ac
    const progressId = appendLocal('assistant', '⏳ 正在抓取热点…', 'streaming')

    void runHotspotDigInPlace({
      form,
      signal: ac.signal,
      onProgress: (text) => patchLocal(progressId, text, 'streaming'),
      onDone: ({ count, items, runId, via, digEvidence }) => {
        digRunningRef.current = false
        setDigBusy(false)
        const req = (digEvidence?.request || {}) as Record<string, unknown>
        const org = (digEvidence?.org_profile_snapshot || {}) as Record<
          string,
          unknown
        >
        const evidenceHead = [
          `适配器：${String(digEvidence?.adapter || via)}`,
          digEvidence?.generated_at
            ? `时间：${String(digEvidence.generated_at)}`
            : '',
          via === 'workflow' && runId ? `run：${runId.slice(0, 8)}` : '通道：直接挖掘',
          req.categories
            ? `方向：${Array.isArray(req.categories) ? req.categories.join('、') : String(req.categories)}`
            : '',
          req.keywords ? `关键词：${String(req.keywords)}` : '',
          req.exclude_keywords
            ? `排除：${String(req.exclude_keywords)}`
            : '',
          org.industry ? `画像行业：${String(org.industry)}` : '',
          org.product_focus ? `产品：${String(org.product_focus)}` : '',
          org.target_audience ? `受众：${String(org.target_audience)}` : '',
          org.target_region ? `地域：${String(org.target_region)}` : '',
          digEvidence?.provenance_note
            ? `说明：${String(digEvidence.provenance_note)}`
            : '',
        ]
          .filter(Boolean)
          .join('\n')

        const lines = items
          .slice(0, 12)
          .map((h, i) => {
            const topic = h.core_topic || h.title
            const desc = h.short_desc || h.summary || ''
            const ev = h.evidence
            const parts = [
              `${i + 1}. [${h.source || h.category || '热点'}] ${topic}`,
              desc ? `   摘要：${desc}` : '',
              `   热度：${h.hot_score ?? h.score ?? '-'} · 趋势：${h.hot_trend || '-'} · 竞争：${h.competition_level || '-'} · 排名：${h.rank ?? i + 1}`,
              h.emotion_tag?.length
                ? `   情绪：${h.emotion_tag.join('、')}`
                : '',
              h.main_keywords?.length
                ? `   关键词：${h.main_keywords.join('、')}`
                : '',
              h.extend_keywords?.length
                ? `   延伸词：${h.extend_keywords.join('、')}`
                : '',
              h.risk_tag?.length ? `   风险：${h.risk_tag.join('、')}` : '',
              (() => {
                const excerpt =
                  (h as { 原文摘录?: string }).原文摘录 ||
                  ev?.raw_excerpt ||
                  ''
                const label = ev?.source_label || h.source || ''
                const links = h.reference_material_links || []
                const hasLink = links.length > 0 || !!ev?.source_url
                const note = ev?.crawl_note || ''
                const hideNote =
                  hasLink &&
                  (note.startsWith('列表页抓取自') || note.includes('条目链接：'))
                const lines: string[] = []
                if (label) lines.push(`   来源证据：${label}`)
                if (excerpt) lines.push(`   原文摘录：${excerpt}`)
                if (note && !hideNote) lines.push(`   采集说明：${note}`)
                return lines.join('\n')
              })(),
            ]
            return parts.filter(Boolean).join('\n')
          })
          .join('\n\n')

        const meta = [
          `✅ 已抓取 ${count} 条热点`,
          via === 'workflow' && runId ? `（run ${runId.slice(0, 8)}）` : '（直接挖掘）',
          '，已写入今日合集。',
          '\n\n[查看明细]',
          evidenceHead || lines
            ? `\n\n<<<DIG>>>\n【抓取条件与证据】\n${evidenceHead}\n\n【条目明细】\n${lines}\n<<<END>>>`
            : '',
        ].join('')
        patchLocal(progressId, meta, 'done')
        void postChatNote({
          session_id: WORKSPACE_CHAT_SESSION,
          content: meta,
          client_message_id: progressId,
          role: 'assistant',
        }).catch(() => undefined)
      },
      onError: (message) => {
        digRunningRef.current = false
        setDigBusy(false)
        patchLocal(progressId, `❌ 抓取失败：${message}`, 'error')
      },
    })
  }

  const openHotspotDigDialog = () => {
    if (digRunningRef.current) {
      appendLocal('assistant', '已有抓取任务进行中，请稍候…')
      return
    }
    setDigOpen(true)
  }

  const openScriptGenDialog = () => {
    if (scriptRunningRef.current) {
      appendLocal('assistant', '已有口播生成任务进行中，请稍候…')
      return
    }
    setScriptOpen(true)
  }

  const startScriptGen = (form: ScriptGenFormValues) => {
    if (scriptRunningRef.current) {
      appendLocal('assistant', '已有口播生成任务进行中，请稍候…')
      return
    }
    scriptRunningRef.current = true
    setScriptBusy(true)
    const progressId = appendLocal(
      'assistant',
      '⏳ 正在生成口播稿…',
      'streaming',
    )
    void runScriptGenInPlace({
      form,
      onProgress: (t) => patchLocal(progressId, t, 'streaming'),
      onDone: ({ script, styleIsDefault, artifactId }) => {
        scriptRunningRef.current = false
        setScriptBusy(false)
        const head = [
          '✅ 口播稿已生成',
          styleIsDefault ? '（默认风格）' : '',
          artifactId ? '，已写入内容库。' : '。',
          '\n\n<<<SCRIPT>>>\n',
          script,
          '\n<<<END>>>',
        ].join('')
        patchLocal(progressId, head, 'done')
        void postChatNote({
          session_id: WORKSPACE_CHAT_SESSION,
          content: head,
          client_message_id: progressId,
          role: 'assistant',
        }).catch(() => undefined)
      },
      onError: (message) => {
        scriptRunningRef.current = false
        setScriptBusy(false)
        patchLocal(progressId, `❌ 口播生成失败：${message}`, 'error')
      },
    })
  }

  useEffect(() => {
    if (!triggerKind || !triggerNonce) return
    clearTrigger()
    if (triggerKind === 'hotspot') {
      openHotspotDigDialog()
    } else if (triggerKind === 'script') {
      openScriptGenDialog()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only react to nonce
  }, [triggerNonce, triggerKind, clearTrigger])

  const onSend = async () => {
    const text = input.trim()
    if (!text) return
    if (streaming) {
      abort()
    }
    setInput('')
    await send(text, {
      session_id: WORKSPACE_CHAT_SESSION,
      ...(modelId ? { model: modelId } : {}),
      temperature,
      ...(maxTokens > 0 ? { max_tokens: maxTokens } : {}),
    })
  }

  const onStop = () => {
    abort()
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void onSend()
    }
  }

  const renderDigBody = (content: string, msgId: string) => {
    if (content.includes('<<<SCRIPT>>>')) {
      const main = content.split('<<<SCRIPT>>>')[0].trim()
      const script =
        content.split('<<<SCRIPT>>>')[1]?.split('<<<END>>>')[0]?.trim() || ''
      // 默认展开口播正文；用户可收起
      const open = expandedDig[msgId] !== false
      return (
        <>
          {main}
          {script ? (
            <div style={{ marginTop: 8 }}>
              <button
                type="button"
                className="nav-tab"
                style={{ fontSize: 12 }}
                onClick={() =>
                  setExpandedDig((s) => ({
                    ...s,
                    [msgId]: !(s[msgId] !== false),
                  }))
                }
              >
                {open ? '收起口播' : '查看口播'}
              </button>
              {open ? (
                <pre
                  className="chat-dig-detail"
                  style={{ fontSize: 15, lineHeight: 1.75 }}
                >
                  {script}
                </pre>
              ) : null}
            </div>
          ) : null}
        </>
      )
    }
    const hasDig = content.includes('<<<DIG>>>')
    if (!hasDig) {
      return content.replace('[查看明细]', '')
    }
    const open = !!expandedDig[msgId]
    const main = content
      .split('<<<DIG>>>')[0]
      .replace('[查看明细]', '')
      .trim()
    const detail = content.split('<<<DIG>>>')[1]?.split('<<<END>>>')[0]?.trim() || ''
    return (
      <>
        {main}
        {detail ? (
          <div style={{ marginTop: 8 }}>
            <button
              type="button"
              className="nav-tab"
              style={{ fontSize: 12 }}
              onClick={() =>
                setExpandedDig((s) => ({ ...s, [msgId]: !s[msgId] }))
              }
            >
              {open ? '收起明细' : '查看明细'}
            </button>
            {open ? (
              <pre
                className="chat-dig-detail"
                style={{ fontSize: 15, lineHeight: 1.75 }}
              >
                {detail}
              </pre>
            ) : null}
          </div>
        ) : null}
      </>
    )
  }

  const renderMessageContent = useCallback(
    (msg: MessageProps) => {
      const text = String(msg.content?.text ?? '')
      const status = msg.content?.status as ChatMessage['status'] | undefined
      const isUser = msg.position === 'right'
      const body = !text && status === 'streaming' ? '…' : text

      const cid = String(msg._id)
      const st = feedbackByMsg[cid]
      const liked = st?.reaction?.type === 'helpful'
      const disliked = st?.reaction?.type === 'irrelevant'
      const bookmarked = !!st?.bookmark

      return (
        <div className={isUser ? 'chat-bubble-wrap is-user' : 'chat-bubble-wrap is-ai'}>
          <Bubble>
            {isUser ? (
              <div className="chat-bubble-plain">{body}</div>
            ) : (
              <div className="chat-bubble-md">
                {body.includes('<<<DIG>>>') ||
                body.includes('<<<SCRIPT>>>') ||
                body.includes('[查看明细]') ? (
                  <div className="chat-bubble-plain">{renderDigBody(body, cid)}</div>
                ) : (
                  <ReactMarkdown>{body}</ReactMarkdown>
                )}
                {status === 'error' && !body.includes('抓取失败') ? (
                  <div className="chat-bubble-error">发送失败</div>
                ) : null}
              </div>
            )}
          </Bubble>
          {!isUser && status === 'done' ? (
            <div className="chat-bubble-actions" data-client-message-id={cid}>
              <button
                type="button"
                className="chat-bubble-action-btn"
                title="复制"
                aria-label="复制"
                onClick={() => void copyText(text)}
              >
                <Copy size={15} strokeWidth={1.75} />
              </button>
              <button
                type="button"
                className={`chat-bubble-action-btn${liked ? ' is-liked' : ''}`}
                title="有帮助"
                aria-label="有帮助"
                aria-pressed={liked}
                onClick={() => void toggleReaction(cid, 'helpful', text)}
              >
                <ThumbsUp size={15} strokeWidth={1.75} fill={liked ? 'currentColor' : 'none'} />
              </button>
              <button
                type="button"
                className={`chat-bubble-action-btn${disliked ? ' is-disliked' : ''}`}
                title="不太对"
                aria-label="不太对"
                aria-pressed={disliked}
                onClick={() => {
                  if (disliked) {
                    void toggleReaction(cid, 'irrelevant', text)
                    return
                  }
                  setDislikeCid(cid)
                }}
              >
                <ThumbsDown size={15} strokeWidth={1.75} fill={disliked ? 'currentColor' : 'none'} />
              </button>
              <button
                type="button"
                className={`chat-bubble-action-btn${bookmarked ? ' is-bookmarked' : ''}`}
                title="收藏"
                aria-label="收藏"
                aria-pressed={bookmarked}
                onClick={() => void toggleBookmark(cid, text)}
              >
                <Bookmark
                  size={15}
                  strokeWidth={1.75}
                  fill={bookmarked ? 'currentColor' : 'none'}
                />
              </button>
            </div>
          ) : null}
        </div>
      )
    },
    [expandedDig, feedbackByMsg, copyText, toggleReaction, toggleBookmark],
  )

  return (
    <>
      <div className="chat-area">
        <div className="chat-messages chatui-message-host">
          {historyError ? (
            <div style={{ fontSize: 12, color: 'var(--color-danger)', padding: 8 }}>
              历史加载失败：{historyError}
            </div>
          ) : null}
          {messages.length === 0 ? (
            <div className="empty-state">
              <div style={{ fontSize: 40, opacity: 0.35, color: 'var(--color-primary-500)' }}>
                ✦
              </div>
              <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--color-gray-700)' }}>
                开始一段新对话
              </div>
              <div style={{ fontSize: 13, color: 'var(--color-gray-500)' }}>
                可用「记忆」查看生效记忆与画像，或「收藏」查看已收藏的回答
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                {!contextOpen ? (
                  <button
                    type="button"
                    className="nav-tab"
                    onClick={() => {
                      setBookmarksOpen(false)
                      setContextOpen(true)
                    }}
                  >
                    打开记忆面板
                  </button>
                ) : null}
                {!bookmarksOpen ? (
                  <button
                    type="button"
                    className="nav-tab"
                    onClick={() => {
                      setContextOpen(false)
                      setHistoryOpen(false)
                      setBookmarksOpen(true)
                    }}
                  >
                    我的收藏
                  </button>
                ) : null}
                {!historyOpen ? (
                  <button
                    type="button"
                    className="nav-tab"
                    onClick={() => {
                      setContextOpen(false)
                      setBookmarksOpen(false)
                      setHistoryOpen(true)
                    }}
                  >
                    对话历史
                  </button>
                ) : null}
              </div>
            </div>
          ) : (
            <PullToRefresh
              ref={ptrRef as never}
              onRefresh={hasMore ? onLoadOlder : undefined}
              onScroll={onMessagesScroll}
              loadMoreText={hasMore ? '加载更早的消息…' : '已是全部历史'}
            >
              {/* PullToRefresh requires a single child (Children.only) */}
              <div className="chat-messages-inner">
                {messages.map((msg) => (
                  <Message
                    key={msg.id}
                    _id={msg.id}
                    type="text"
                    content={{ text: msg.content, status: msg.status }}
                    position={msg.role === 'user' ? 'right' : 'left'}
                    user={{ name: msg.role === 'user' ? '你' : 'N' }}
                    renderMessageContent={renderMessageContent}
                  />
                ))}
                <div ref={endRef} />
              </div>
            </PullToRefresh>
          )}
        </div>

        <div className="chat-input-area">
          <div className="chat-wf-shortcuts" aria-label="常用工作流">
            {(
              [
                { id: 'hotspot', label: '抓取热点', soon: false },
                { id: 'script', label: '生成口播稿', soon: false },
                { id: 'article', label: '生成宣传稿', soon: true },
                { id: 'ppt', label: '生成 PPT', soon: true },
                { id: 'chart', label: '生成图表', soon: true },
              ] as const
            ).map((wf, i, arr) => (
              <span key={wf.id} className="chat-wf-shortcut-wrap">
                <button
                  type="button"
                  className="chat-wf-shortcut"
                  onClick={() => {
                    if (wf.soon) {
                      setWfToast('该工作流即将开放')
                      window.setTimeout(() => setWfToast(null), 2000)
                      return
                    }
                    if (wf.id === 'hotspot') openHotspotDigDialog()
                    else if (wf.id === 'script') openScriptGenDialog()
                  }}
                >
                  {wf.label}
                </button>
                {i < arr.length - 1 ? (
                  <span className="chat-wf-shortcut-sep" aria-hidden>
                    ,
                  </span>
                ) : null}
              </span>
            ))}
          </div>
          {wfToast ? <div className="chat-wf-toast">{wfToast}</div> : null}
          <div className="input-wrapper">
            <textarea
              ref={textareaRef}
              className="input-textarea"
              placeholder={
                digBusy
                  ? '热点抓取进行中…可继续发消息（不中断抓取）'
                  : streaming
                    ? '生成中…可继续输入；Enter 将停止当前回复并发送新消息'
                    : '输入你的问题，Enter 发送 · Shift+Enter 换行'
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
            />
            <div className="input-footer">
              <div className="input-actions-left">
                <button
                  type="button"
                  className="input-action-btn with-label"
                  onClick={() => setDayCollectionOpen(true)}
                >
                  今日热点集合
                </button>
                <button
                  type="button"
                  className="input-action-btn with-label"
                  onClick={() => {
                    if (contextOpen) {
                      setContextOpen(false)
                    } else {
                      setBookmarksOpen(false)
                      setHistoryOpen(false)
                      setContextOpen(true)
                    }
                  }}
                >
                  {contextOpen ? '收起记忆' : '记忆'}
                </button>
                <button
                  type="button"
                  className="input-action-btn with-label"
                  onClick={() => {
                    if (bookmarksOpen) {
                      setBookmarksOpen(false)
                    } else {
                      setContextOpen(false)
                      setHistoryOpen(false)
                      setBookmarksOpen(true)
                    }
                  }}
                >
                  {bookmarksOpen ? '收起收藏' : '收藏'}
                </button>
                <button
                  type="button"
                  className="input-action-btn with-label"
                  onClick={() => {
                    if (historyOpen) {
                      setHistoryOpen(false)
                    } else {
                      setContextOpen(false)
                      setBookmarksOpen(false)
                      setHistoryOpen(true)
                    }
                  }}
                >
                  {historyOpen ? '收起历史' : '历史'}
                </button>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                {modelId ? (
                  <span className="input-hint" title={modelId}>
                    模型：{modelId}
                  </span>
                ) : null}
                {streaming ? (
                  <button
                    type="button"
                    className="send-btn"
                    onClick={onStop}
                    aria-label="停止生成"
                    title="停止生成（不影响后台抓取）"
                    style={{ background: 'var(--color-danger, #dc2626)' }}
                  >
                    ■
                  </button>
                ) : (
                  <button
                    type="button"
                    className="send-btn"
                    onClick={() => void onSend()}
                    disabled={!input.trim()}
                    aria-label="发送"
                  >
                    ↑
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      <ContextPanel
        open={contextOpen}
        onClose={() => setContextOpen(false)}
      />
      <BookmarksDrawer
        open={bookmarksOpen}
        onClose={() => setBookmarksOpen(false)}
        onChanged={() => void hydrateFeedback(WORKSPACE_CHAT_SESSION)}
      />
      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
      />
      <HotspotDayCollectionDialog
        open={dayCollectionOpen}
        onOpenChange={setDayCollectionOpen}
      />
      <HotspotDigDialog
        open={digOpen}
        onOpenChange={setDigOpen}
        submitting={digBusy}
        onConfirm={(values) => {
          setDigOpen(false)
          startHotspotDig(values)
        }}
      />
      <ScriptGenDialog
        open={scriptOpen}
        onOpenChange={setScriptOpen}
        submitting={scriptBusy}
        onConfirm={(values) => {
          setScriptOpen(false)
          startScriptGen(values)
        }}
      />
      <DislikeReasonDialog
        open={dislikeCid != null}
        submitting={feedbackBusy != null && dislikeCid != null}
        onOpenChange={(open) => {
          if (!open) setDislikeCid(null)
        }}
        onSubmit={(reasonIds, note) => {
          if (!dislikeCid) return
          void submitDislike(dislikeCid, reasonIds, note).then((ok) => {
            if (ok) setDislikeCid(null)
          })
        }}
      />
    </>
  )
}
