import { useEffect, useRef, useState } from 'react'

import {
  agentChat,
  agentHistory,
  agentStatus,
  agentTools,
  type AgentTool,
} from '@/api/agent'
import { formatApiError } from '@/api/http'
import { ForbiddenBanner } from '@/components/role/RoleSwitcher'
import { Badge } from '@/components/ui/badge'
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
import { useAuthStore } from '@/stores/authStore'

function toolsList(data: AgentTool[] | Record<string, unknown> | null): AgentTool[] {
  if (!data) return []
  if (Array.isArray(data)) return data
  if (Array.isArray((data as { tools?: unknown }).tools)) {
    return (data as { tools: AgentTool[] }).tools
  }
  return Object.entries(data).map(([name, v]) =>
    typeof v === 'object' && v
      ? { name, ...(v as object) }
      : { name, description: String(v) },
  )
}

export default function AgentPanel() {
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const [userId, setUserId] = useState('fe-agent')
  const [message, setMessage] = useState('你好，列出可用工具')
  const [status, setStatus] = useState<Record<string, unknown> | null>(null)
  const [tools, setTools] = useState<AgentTool[]>([])
  const [chatResult, setChatResult] = useState<unknown>(null)
  const [history, setHistory] = useState<unknown>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const skip = useRef(true)

  const loadMeta = async () => {
    setErr('')
    try {
      const [s, t] = await Promise.all([agentStatus(), agentTools()])
      setStatus(s.data)
      setTools(toolsList(t.data))
    } catch (e) {
      setErr(formatApiError(e, 'chat:write'))
    }
  }

  useEffect(() => {
    void loadMeta()
  }, [])

  useEffect(() => {
    if (skip.current) {
      skip.current = false
      return
    }
    setChatResult(null)
    setHistory(null)
    void loadMeta()
  }, [roleEpoch])

  const onChat = async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await agentChat({
        user_id: userId.trim() || 'fe-agent',
        message: message.trim(),
      })
      setChatResult(r.data)
    } catch (e) {
      setErr(formatApiError(e, 'chat:write'))
    } finally {
      setBusy(false)
    }
  }

  const onHistory = async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await agentHistory(userId.trim() || 'fe-agent')
      setHistory(r.data)
    } catch (e) {
      setErr(formatApiError(e, 'chat:write'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Agent</h1>
        <p className="text-muted-foreground text-xs">
          /agent/status · tools · chat · history（嵌套链见 30.25）
        </p>
      </div>
      <ForbiddenBanner />
      {err ? (
        <p className="text-destructive text-sm" role="alert">
          {err}
        </p>
      ) : null}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-sm font-semibold">Status</CardTitle>
            <CardDescription className="text-xs">GET /agent/status</CardDescription>
          </div>
          <Button type="button" size="sm" variant="outline" onClick={() => void loadMeta()}>
            刷新
          </Button>
        </CardHeader>
        <CardContent>
          <pre className="overflow-auto rounded-lg border border-border p-2 text-xs">
            {status ? JSON.stringify(status, null, 2) : '—'}
          </pre>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Tools</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {tools.length === 0 ? (
            <p className="text-muted-foreground text-xs">无工具或未加载</p>
          ) : (
            tools.map((t, i) => (
              <Badge key={`${t.name ?? i}`} variant="outline" title={String(t.description || '')}>
                {String(t.name || `tool-${i}`)}
              </Badge>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Chat</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="ag-uid">user_id</Label>
              <Input
                id="ag-uid"
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ag-msg">message</Label>
              <Input
                id="ag-msg"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
              />
            </div>
          </div>
          <div className="flex gap-2">
            <Button type="button" disabled={busy} onClick={() => void onChat()}>
              发送 /agent/chat
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => void onHistory()}
            >
              History
            </Button>
          </div>
          {chatResult ? (
            <pre className="overflow-auto rounded-lg border border-border p-2 text-xs">
              {JSON.stringify(chatResult, null, 2)}
            </pre>
          ) : null}
          {history ? (
            <pre className="overflow-auto rounded-lg border border-border p-2 text-xs">
              {JSON.stringify(history, null, 2)}
            </pre>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
