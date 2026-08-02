import { useEffect, useRef, useState } from 'react'

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
import { useSSEStream } from '@/hooks/useSSEStream'
import { useAuthStore } from '@/stores/authStore'

type Props = {
  title?: string
  endpoint?: string
  /** 演示用：不传则走真实 SSE */
  demoText?: string
}

export function SSEPanel({
  title = 'SSE 流式',
  endpoint = '/chat/streaming',
  demoText,
}: Props) {
  const role = useAuthStore((s) => s.activeRole)
  const { start, abort } = useSSEStream()
  const [message, setMessage] = useState('hello')
  const [text, setText] = useState('')
  const [live, setLive] = useState(false)
  const [status, setStatus] = useState<StatusKind>('idle')
  const [hint, setHint] = useState('空态 — 输入消息后开始流式')
  const demoAbort = useRef(false)
  const liveTimer = useRef<number | null>(null)

  useEffect(() => () => abort(), [abort])

  const flashLive = () => {
    setLive(true)
    if (liveTimer.current) window.clearTimeout(liveTimer.current)
    liveTimer.current = window.setTimeout(() => setLive(false), 600)
  }

  const runDemo = async () => {
    demoAbort.current = false
    setText('')
    setStatus('pending')
    setHint('演示打字机…')
    const src = demoText || 'ContextGate SSE demo stream.'
    for (const ch of src) {
      if (demoAbort.current) {
        setStatus('warning')
        setHint('已 abort')
        return
      }
      setText((t) => t + ch)
      flashLive()
      await new Promise((r) => setTimeout(r, 28))
    }
    setStatus('success')
    setHint('完成')
  }

  const onStart = async () => {
    if (demoText !== undefined) {
      await runDemo()
      return
    }
    setText('')
    setStatus('pending')
    setHint('流式中（: ping 被解析器忽略；● 表示收到 token）')
    await start(
      endpoint,
      { method: 'POST', body: JSON.stringify({ message }) },
      {
        onToken: (t) => {
          flashLive()
          setText((prev) => prev + t)
        },
        onAbort: (reason) => {
          setStatus('warning')
          setHint(`abort: ${reason}`)
        },
        onError: (code, msg) => {
          setStatus('error')
          setHint(`[${code}] ${msg}`)
        },
        onDone: () => {
          setStatus('success')
          setHint('完成')
        },
      },
    )
  }

  const onAbortClick = () => {
    demoAbort.current = true
    abort()
    setStatus('warning')
    setHint('已 abort')
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div>
          <CardTitle className="text-sm font-semibold">{title}</CardTitle>
          <CardDescription className="text-muted-foreground text-xs">
            {endpoint} · {role}
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={status} />
          <span
            className={live ? 'text-primary text-xs' : 'text-muted-foreground text-xs'}
            aria-live="polite"
            title="流活动指示（token 到达时闪烁；SSE : ping 已忽略）"
          >
            {live ? '● live' : '·'}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1">
          <Label htmlFor="sse-msg">消息</Label>
          <Input
            id="sse-msg"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
        </div>
        <div className="flex gap-2">
          <Button type="button" onClick={() => void onStart()} disabled={status === 'pending'}>
            开始
          </Button>
          <Button type="button" variant="outline" onClick={onAbortClick}>
            Abort
          </Button>
        </div>
        <p className="text-muted-foreground text-xs">{hint}</p>
        <div className="min-h-28 whitespace-pre-wrap rounded-lg border border-border bg-background p-3 font-mono text-sm">
          {text || <span className="text-muted-foreground">（等待 token…）</span>}
          {status === 'pending' ? (
            <span className="animate-pulse text-primary">▍</span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}
