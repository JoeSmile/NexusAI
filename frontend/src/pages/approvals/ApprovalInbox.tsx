import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { formatApiError } from '@/api/http'
import {
  approveRequest,
  listApprovalInbox,
  rejectRequest,
  type ApprovalRequest,
} from '@/api/workflowApprovals'
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

export default function ApprovalInboxPage() {
  const [items, setItems] = useState<ApprovalRequest[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [rejectReason, setRejectReason] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    setErr('')
    try {
      const res = await listApprovalInbox()
      setItems(res.items ?? [])
    } catch (e) {
      setErr(formatApiError(e, 'workflow:approve_dept'))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function onApprove(item: ApprovalRequest) {
    if (
      !window.confirm(
        `批准后将授权节点「${item.capability_id}」最小权限并恢复运行。确认？`,
      )
    ) {
      return
    }
    setBusy(true)
    setErr('')
    try {
      await approveRequest(item.id)
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'approve'))
    } finally {
      setBusy(false)
    }
  }

  async function onReject(item: ApprovalRequest) {
    const reason = (rejectReason[item.id] || '').trim() || 'rejected'
    setBusy(true)
    setErr('')
    try {
      await rejectRequest(item.id, { reason })
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'reject'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4 p-4">
      <ForbiddenBanner />
      <Card>
        <CardHeader>
          <CardTitle>待办审批</CardTitle>
          <CardDescription>
            可行动的审批队列。事件流通知见「通知」页；角标为通知未读。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {err ? <p className="text-sm text-destructive">{err}</p> : null}
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>
            刷新
          </Button>
          {items.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无待办审批</p>
          ) : (
            items.map((item) => (
              <div key={item.id} className="space-y-2 rounded-md border p-3">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium">
                    {item.workflow_name || item.run_id}
                  </span>
                  <Badge>{item.requestable_mode || 'true'}</Badge>
                  {item.escalated_at ? (
                    <Badge variant="secondary">已升级 tenant_admin</Badge>
                  ) : (
                    <Badge variant="outline">待 dept_manager</Badge>
                  )}
                </div>
                <p className="text-sm text-muted-foreground">
                  节点 {item.node_id} · 能力 {item.capability_id} · 需权限{' '}
                  {item.needed_perm}
                </p>
                <p className="text-sm">申请人：{item.applicant_user_id}</p>
                <p className="text-sm">审批说明：{item.approval_note || '（无）'}</p>
                <p className="text-xs text-muted-foreground">
                  <Link className="underline" to={`/runs/${item.run_id}`}>
                    查看运行
                  </Link>
                </p>
                <div className="flex flex-wrap items-end gap-2 pt-2">
                  <Button
                    size="sm"
                    disabled={busy}
                    onClick={() => void onApprove(item)}
                  >
                    批准
                  </Button>
                  <div className="space-y-1">
                    <Label htmlFor={`rej-${item.id}`}>拒绝理由</Label>
                    <Input
                      id={`rej-${item.id}`}
                      className="h-8 w-48"
                      value={rejectReason[item.id] ?? ''}
                      onChange={(e) =>
                        setRejectReason((m) => ({
                          ...m,
                          [item.id]: e.target.value,
                        }))
                      }
                    />
                  </div>
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={busy}
                    onClick={() => void onReject(item)}
                  >
                    拒绝
                  </Button>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  )
}
