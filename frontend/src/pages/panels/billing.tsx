import { useEffect, useState } from 'react'

import {
  exportUsageCsv,
  fetchUsageDetail,
  fetchUsageSummary,
  fetchWallet,
  rechargeWallet,
  type UsageDetailRow,
  type UsageSummary,
  type WalletSummary,
} from '@/api/billing'
import { formatApiError } from '@/api/http'
import { ForbiddenBanner } from '@/components/role/RoleSwitcher'
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAuthStore } from '@/stores/authStore'

function currentMonth(): string {
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  return `${d.getFullYear()}-${m}`
}

export default function BillingPanel() {
  const role = useAuthStore((s) => s.activeRole)
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const [billingMonth, setBillingMonth] = useState(currentMonth())
  const [credentialKind, setCredentialKind] = useState('')
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [rows, setRows] = useState<UsageDetailRow[]>([])
  const [wallet, setWallet] = useState<WalletSummary | null>(null)
  const [rechargeAmount, setRechargeAmount] = useState('')
  const [referenceNo, setReferenceNo] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const canRecharge = role === 'tenant_admin' || role === 'super_admin'

  const query = {
    billing_month: billingMonth.trim() || undefined,
    credential_kind: credentialKind.trim() || undefined,
    limit: 50,
  }

  const load = async () => {
    setBusy(true)
    setErr('')
    try {
      const [s, d, w] = await Promise.all([
        fetchUsageSummary(query),
        fetchUsageDetail(query),
        fetchWallet().catch(() => null),
      ])
      setSummary(s)
      setRows(d)
      setWallet(w)
    } catch (e) {
      setSummary(null)
      setRows([])
      setErr(formatApiError(e, 'billing:read'))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refresh on role switch
  }, [roleEpoch])

  const onExport = async () => {
    setBusy(true)
    setErr('')
    try {
      await exportUsageCsv(query)
    } catch (e) {
      setErr(formatApiError(e, 'billing:export'))
    } finally {
      setBusy(false)
    }
  }

  const onRecharge = async () => {
    const amount = Number(rechargeAmount)
    if (!amount || amount <= 0 || !referenceNo.trim()) {
      setErr('请填写有效金额与转账凭证号')
      return
    }
    setBusy(true)
    setErr('')
    try {
      const res = await rechargeWallet(amount, referenceNo.trim())
      setWallet((prev) =>
        prev
          ? { ...prev, balance: res.balance_after }
          : {
              tenant_id: res.tenant_id,
              balance: res.balance_after,
              currency: 'CNY',
              transactions: [],
            },
      )
      setRechargeAmount('')
      setReferenceNo('')
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'billing:recharge'))
    } finally {
      setBusy(false)
    }
  }

  const totals = summary?.totals

  return (
    <div className="space-y-4 p-4">
      <ForbiddenBanner />
      <Card>
        <CardHeader>
          <CardTitle>账户余额</CardTitle>
          <CardDescription>
            预付费钱包（需设置 <code>BILLING_WALLET_ENABLED=1</code> 后启用扣费硬闸）。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="text-3xl font-semibold">
            {wallet != null ? `¥${wallet.balance.toFixed(2)} ${wallet.currency}` : '—'}
          </div>
          {canRecharge ? (
            <div className="rounded-lg border border-border p-4 space-y-3">
              <p className="text-sm text-muted-foreground">
                对公转账后由管理员入账。收款账户：[律师审] 开户行 / 账号 / 户名。
              </p>
              <div className="flex flex-wrap gap-4">
                <div className="space-y-1">
                  <Label htmlFor="recharge-amount">充值金额 (CNY)</Label>
                  <Input
                    id="recharge-amount"
                    type="number"
                    min="0"
                    step="0.01"
                    value={rechargeAmount}
                    onChange={(e) => setRechargeAmount(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="reference-no">转账凭证号</Label>
                  <Input
                    id="reference-no"
                    value={referenceNo}
                    onChange={(e) => setReferenceNo(e.target.value)}
                  />
                </div>
                <div className="flex items-end">
                  <Button type="button" disabled={busy} onClick={() => void onRecharge()}>
                    提交入账
                  </Button>
                </div>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>消费账单</CardTitle>
          <CardDescription>
            计费级流水（与审计日志解耦）。公司 Key 记费；BYOK 仅记账不归平台收费。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-4">
            <div className="space-y-1">
              <Label htmlFor="billing-month">账单月份</Label>
              <Input
                id="billing-month"
                placeholder="YYYY-MM"
                value={billingMonth}
                onChange={(e) => setBillingMonth(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="cred-kind">凭证类型</Label>
              <Input
                id="cred-kind"
                placeholder="company / byok（留空=全部）"
                value={credentialKind}
                onChange={(e) => setCredentialKind(e.target.value)}
              />
            </div>
            <div className="flex items-end gap-2">
              <Button type="button" disabled={busy} onClick={() => void load()}>
                查询
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => void onExport()}
              >
                导出 CSV
              </Button>
            </div>
          </div>
          {err ? <p className="text-sm text-red-600">{err}</p> : null}
          <div className="grid gap-3 sm:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>调用次数</CardDescription>
                <CardTitle className="text-2xl">{totals?.calls ?? '—'}</CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>输入 Token</CardDescription>
                <CardTitle className="text-2xl">
                  {totals?.input_tokens ?? '—'}
                </CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>输出 Token</CardDescription>
                <CardTitle className="text-2xl">
                  {totals?.output_tokens ?? '—'}
                </CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>总成本 (CNY)</CardDescription>
                <CardTitle className="text-2xl">
                  {totals != null ? totals.cost.toFixed(4) : '—'}
                </CardTitle>
              </CardHeader>
            </Card>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>时间</TableHead>
                <TableHead>模型</TableHead>
                <TableHead>凭证</TableHead>
                <TableHead>Token</TableHead>
                <TableHead>成本</TableHead>
                <TableHead>Trace</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-muted-foreground">
                    {busy ? '加载中…' : '暂无记录'}
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="text-xs">
                      {r.created_at?.replace('T', ' ').slice(0, 19) ?? '—'}
                    </TableCell>
                    <TableCell>{r.model}</TableCell>
                    <TableCell>{r.credential_kind}</TableCell>
                    <TableCell>
                      {r.input_tokens}+{r.output_tokens}
                    </TableCell>
                    <TableCell>{r.cost.toFixed(6)}</TableCell>
                    <TableCell className="max-w-[8rem] truncate text-xs">
                      {r.trace_id ?? '—'}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
