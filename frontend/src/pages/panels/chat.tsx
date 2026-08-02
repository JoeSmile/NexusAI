import { useEffect, useRef, useState } from 'react'

import { postChat, CHAT_STREAM_ENDPOINT } from '@/api/chat'
import { RequestPanel } from '@/components/panels/RequestPanel'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { StatusBadge, type StatusKind } from '@/components/ui/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { useSSEStream } from '@/hooks/useSSEStream'
import { useAuthStore } from '@/stores/authStore'

/** Chat 面板 — /chat JSON + /chat/streaming 双格式（Task 30.16）。 */
export default function ChatPanel() {
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const { start, abort } = useSSEStream()
  const [message, setMessage] = useState('你好')
  const [text, setText] = useState('')
  const [meta, setMeta] = useState<Record<string, unknown>>({})
  const [live, setLive] = useState(false)
  const [path, setPath] = useState<'short' | 'long' | null>(null)
  const [status, setStatus] = useState<StatusKind>('idle')
  const [hint, setHint] = useState('空态 — 发「你好」多走短路径 JSON；长问题走 SSE')
  const liveTimer = useRef<number | null>(null)
  const skipEpoch = useRef(true)

  useEffect(() => () => abort(), [abort])

  useEffect(() => {
    if (skipEpoch.current) {
      skipEpoch.current = false
      return
    }
    abort()
    setText('')
    setMeta({})
    setPath(null)
    setStatus('idle')
    setHint('角色已切换 — 请重新发送')
  }, [roleEpoch, abort])

  const flashLive = () => {
    setLive(true)
    if (liveTimer.current) window.clearTimeout(liveTimer.current)
    liveTimer.current = window.setTimeout(() => setLive(false), 500)
  }

  const onStream = async () => {
    const msg = message.trim()
    if (!msg) return
    setText('')
    setMeta({})
    setPath(null)
    setStatus('pending')
    setHint('请求中…')
    await start(
      CHAT_STREAM_ENDPOINT,
      {
        method: 'POST',
        body: JSON.stringify({ message: msg, session_id: 'fe-chat' }),
      },
      {
        onToken: (t) => {
          flashLive()
          setText((prev) => prev + t)
        },
        onAbort: (reason) => {
          setStatus('warning')
          setHint(`abort: ${reason}`)
        },
        onRetraction: (reason) => {
          setStatus('warning')
          setHint(`retraction: ${reason}`)
        },
        onError: (code, m) => {
          setStatus('error')
          setHint(`[${code}] ${m}`)
        },
        onDone: (m) => {
          const p = m?.path === 'short' ? 'short' : 'long'
          setPath(p)
          setMeta(m || {})
          setStatus('success')
          setHint(p === 'short' ? '短路径 JSON 完成' : '长路径 SSE 完成')
        },
      },
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Chat</h1>
        <p className="text-muted-foreground text-xs">
          /chat/streaming（双格式）· /chat（JSON 对照）
        </p>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-2">
          <div>
            <CardTitle className="text-sm font-semibold">流式对话</CardTitle>
            <CardDescription className="text-muted-foreground text-xs">
              {CHAT_STREAM_ENDPOINT}
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={status} />
            {path === 'short' ? (
              <Badge variant="success">短路径</Badge>
            ) : null}
            {path === 'long' ? (
              <Badge variant="default">长路径 SSE</Badge>
            ) : null}
            <span
              className={live ? 'text-primary text-xs' : 'text-muted-foreground text-xs'}
              title="token 活动指示（: ping 已忽略）"
            >
              {live ? '● live' : '·'}
            </span>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="chat-msg">消息</Label>
            <Input
              id="chat-msg"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="你好 / 请写一篇长文…"
            />
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              onClick={() => void onStream()}
              disabled={status === 'pending'}
            >
              发送流式
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                abort()
                setStatus('warning')
                setHint('已 Stop')
              }}
            >
              Stop
            </Button>
          </div>
          <p className="text-muted-foreground text-xs">{hint}</p>
          <div className="min-h-28 whitespace-pre-wrap rounded-lg border border-border bg-background p-3 font-mono text-sm">
            {text || <span className="text-muted-foreground">（等待响应…）</span>}
            {status === 'pending' ? (
              <span className="animate-pulse text-primary">▍</span>
            ) : null}
          </div>
          {Object.keys(meta).length > 0 ? (
            <pre className="overflow-auto rounded-lg border border-border bg-card p-2 text-xs">
              {JSON.stringify(
                {
                  path: meta.path,
                  finish_reason: meta.finish_reason,
                  capability_id: meta.capability_id,
                  cost: meta.total_cost ?? meta.cost,
                  trace_id: meta.trace_id,
                  cost_source: meta.cost_source,
                },
                null,
                2,
              )}
            </pre>
          ) : null}
        </CardContent>
      </Card>

      <RequestPanel
        title="对照：POST /chat（JSON）"
        description="非 streaming 管线；展示 finish_reason / cost / trace_id"
        endpoint="/chat"
        method="POST"
        fields={[
          {
            name: 'message',
            label: 'message',
            defaultValue: '你好',
          },
        ]}
        onSend={async (v) => postChat(v.message || '你好')}
        renderResult={(data) => (
          <pre className="overflow-auto text-xs">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}
      />
    </div>
  )
}
