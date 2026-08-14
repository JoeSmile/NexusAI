import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { formatApiError } from '@/api/http'
import {
  listNotificationInbox,
  markNotificationRead,
  type NotificationItem,
} from '@/api/notifications'
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

const TYPE_LABEL: Record<string, string> = {
  'hang.pending': '待批',
  'hang.approved': '已批准',
  'hang.rejected': '已拒绝',
  'hang.escalated': '已升级',
  'hang.cancelled': '已撤销',
  'hang.ttl_reapply': 'TTL 过期重申请',
  'hang.recurring_due': '周期到期',
}

export default function NotificationsPage() {
  const [items, setItems] = useState<NotificationItem[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setErr('')
    try {
      const res = await listNotificationInbox({ limit: 50 })
      setItems(res.items ?? [])
    } catch (e) {
      setErr(formatApiError(e, 'notifications'))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function onRead(item: NotificationItem) {
    if (item.read_at) return
    setBusy(true)
    setErr('')
    try {
      await markNotificationRead(item.id)
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'notifications'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4 p-4">
      <ForbiddenBanner />
      <Card>
        <CardHeader>
          <CardTitle>通知</CardTitle>
          <CardDescription>
            事件流（已批 / 升级 / 撤销等）。可行动的待办审批请到「待办审批」。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {err ? <p className="text-sm text-destructive">{err}</p> : null}
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>
            刷新
          </Button>
          {items.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无通知</p>
          ) : (
            items.map((item) => (
              <div
                key={item.id}
                className="flex flex-col gap-2 rounded-md border p-3 text-sm"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={item.read_at ? 'outline' : 'default'}>
                    {TYPE_LABEL[item.type] || item.type}
                  </Badge>
                  {!item.read_at ? <Badge variant="secondary">未读</Badge> : null}
                  <span className="text-muted-foreground text-xs">
                    {item.created_at || ''}
                  </span>
                </div>
                <p className="text-muted-foreground">
                  {item.payload.request_id
                    ? `request ${item.payload.request_id}`
                    : null}
                  {item.payload.node_id ? ` · 节点 ${item.payload.node_id}` : null}
                </p>
                <div className="flex flex-wrap gap-2">
                  {item.payload.run_id ? (
                    <Link className="underline" to={`/runs/${item.payload.run_id}`}>
                      查看运行
                    </Link>
                  ) : null}
                  {!item.read_at ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => void onRead(item)}
                    >
                      标为已读
                    </Button>
                  ) : null}
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  )
}
