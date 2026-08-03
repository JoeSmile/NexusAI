import { useEffect, useRef, useState } from 'react'

import {
  agentChat,
  agentHistory,
  agentStatus,
  agentTools,
  hubAgentInvokeUrl,
  listHubAgents,
  type AgentTool,
  type HubAgent,
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
import { useSSEStream } from '@/hooks/useSSEStream'
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

function formatChain(chain: string[]): string {
  if (chain.length <= 1) return chain[0] || '—'
  // 展示嵌套段：跳过根，突出子调用
  const nested = chain.slice(1)
  return nested.length ? `调用了 ${nested.join(' → ')}` : chain[0]
}

export default function AgentPanel() {
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const { start, abort } = useSSEStream()
  const [userId, setUserId] = useState('fe-agent')
  const [message, setMessage] = useState('评估供应商合同风险')
  const [hubAgents, setHubAgents] = useState<HubAgent[]>([])
  const [selectedAgent, setSelectedAgent] = useState('vendor-risk-agent')
  const [status, setStatus] = useState<Record<string, unknown> | null>(null)
  const [tools, setTools] = useState<AgentTool[]>([])
  const [streamText, setStreamText] = useState('')
  const [callChain, setCallChain] = useState<string[]>([])
  const [chatResult, setChatResult] = useState<unknown>(null)
  const [history, setHistory] = useState<unknown>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const skip = useRef(true)

  const loadMeta = async () => {
    setErr('')
    try {
      const [s, t, agents] = await Promise.all([
        agentStatus().catch(() => null),
        agentTools().catch(() => null),
        listHubAgents(),
      ])
      if (s) setStatus(s.data)
      if (t) setTools(toolsList(t.data))
      setHubAgents(agents.items || [])
      if (
        agents.items?.length &&
        !agents.items.some((a) => a.id === selectedAgent)
      ) {
        setSelectedAgent(agents.items[0].id)
      }
    } catch (e) {
      setErr(formatApiError(e, 'chat:write'))
    }
  }

  useEffect(() => {
    void loadMeta()
    return () => abort()
  }, [abort])

  useEffect(() => {
    if (skip.current) {
      skip.current = false
      return
    }
    setChatResult(null)
    setHistory(null)
    setStreamText('')
    setCallChain([])
    abort()
    void loadMeta()
  }, [roleEpoch, abort])

  const onHubInvoke = async () => {
    const id = selectedAgent.trim()
    if (!id || !message.trim()) return
    setBusy(true)
    setErr('')
    setStreamText('')
    setCallChain([])
    await start(
      hubAgentInvokeUrl(id),
      {
        method: 'POST',
        body: JSON.stringify({
          message: message.trim(),
          stream: true,
          extra: { user_id: userId.trim() || 'fe-agent' },
        }),
      },
      {
        onToken: (t) => setStreamText((prev) => prev + t),
        onDone: (meta) => {
          const chain = meta?.call_chain
          if (Array.isArray(chain)) {
            setCallChain(chain.map(String))
          }
          setBusy(false)
        },
        onError: (code, m) => {
          setErr(`[${code}] ${m}`)
          setBusy(false)
        },
      },
    )
    setBusy(false)
  }

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
          Hub invoke 嵌套链 · 旧 /agent/* 兼容
        </p>
      </div>
      <ForbiddenBanner />
      {err ? (
        <p className="text-destructive text-sm" role="alert">
          {err}
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Capability Hub Agent</CardTitle>
          <CardDescription className="text-xs">
            POST /api/capabilities/&#123;id&#125;/invoke — 选 vendor-risk-agent 看嵌套链
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="hub-agent">agent</Label>
              <select
                id="hub-agent"
                className="border-input bg-background h-8 w-full rounded-lg border px-2 text-sm"
                value={selectedAgent}
                onChange={(e) => setSelectedAgent(e.target.value)}
              >
                {hubAgents.length === 0 ? (
                  <option value="vendor-risk-agent">vendor-risk-agent（未 seed）</option>
                ) : (
                  hubAgents.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} ({a.id})
                    </option>
                  ))
                )}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="ag-uid">user_id</Label>
              <Input
                id="ag-uid"
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="ag-msg">message</Label>
            <Input
              id="ag-msg"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
          </div>
          <Button type="button" disabled={busy} onClick={() => void onHubInvoke()}>
            流式 invoke（Hub）
          </Button>
          {callChain.length > 0 ? (
            <div className="space-y-2 rounded-lg border border-border p-3">
              <p className="text-xs font-medium">{formatChain(callChain)}</p>
              <div className="flex flex-wrap gap-1">
                {callChain.map((c, i) => (
                  <Badge key={`${c}-${i}`} variant={i === 0 ? 'success' : 'outline'}>
                    {c}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}
          {streamText ? (
            <pre className="max-h-48 overflow-auto rounded-lg border border-border p-2 text-xs whitespace-pre-wrap">
              {streamText}
            </pre>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-sm font-semibold">Status（旧路由）</CardTitle>
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
          <CardTitle className="text-sm font-semibold">Legacy /agent/chat</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Button type="button" variant="outline" disabled={busy} onClick={() => void onChat()}>
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
