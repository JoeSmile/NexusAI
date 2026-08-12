import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  createOrgUnit,
  deleteMembership,
  deleteOrgUnit,
  fetchMyMemberships,
  fetchOrgTree,
  fetchUnitMemberships,
  moveOrgUnit,
  upsertMembership,
  type OrgMembership,
  type OrgUnit,
} from '@/api/org'
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAuthStore } from '@/stores/authStore'

function depthOf(path: string): number {
  return path.split('/').filter(Boolean).length
}

export default function OrgTreePage() {
  const role = useAuthStore((s) => s.activeRole)
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const canWrite = role === 'tenant_admin' || role === 'super_admin'

  const [units, setUnits] = useState<OrgUnit[]>([])
  const [mine, setMine] = useState<OrgMembership[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [members, setMembers] = useState<OrgMembership[]>([])
  const [includeDeleted, setIncludeDeleted] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const [newName, setNewName] = useState('')
  const [newParent, setNewParent] = useState<string>('')
  const [memberUser, setMemberUser] = useState('')
  const [memberRole, setMemberRole] = useState('member')
  const [moveParent, setMoveParent] = useState<string>('')

  const load = useCallback(async () => {
    setErr('')
    setBusy(true)
    try {
      const [tree, me] = await Promise.all([
        fetchOrgTree(includeDeleted),
        fetchMyMemberships(),
      ])
      setUnits(tree)
      setMine(me)
    } catch (e) {
      setUnits([])
      setMine([])
      setErr(formatApiError(e, 'org'))
    } finally {
      setBusy(false)
    }
  }, [includeDeleted])

  useEffect(() => {
    void load()
  }, [load, roleEpoch])

  useEffect(() => {
    if (!selectedId) {
      setMembers([])
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const rows = await fetchUnitMemberships(selectedId)
        if (!cancelled) setMembers(rows)
      } catch (e) {
        if (!cancelled) {
          setMembers([])
          setErr(formatApiError(e, 'org'))
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedId, roleEpoch])

  const sorted = useMemo(
    () => [...units].sort((a, b) => a.path.localeCompare(b.path)),
    [units],
  )

  const onCreate = async () => {
    if (!newName.trim()) return
    setBusy(true)
    setErr('')
    try {
      await createOrgUnit({
        name: newName.trim(),
        parent_id: newParent || null,
      })
      setNewName('')
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'org'))
    } finally {
      setBusy(false)
    }
  }

  const onArchive = async (id: string) => {
    if (
      !window.confirm(
        '将归档该部门：进行中的流程会跑完；之后不能再往该部门挂靠成员/知识。继续？',
      )
    ) {
      return
    }
    setBusy(true)
    try {
      await deleteOrgUnit(id)
      if (selectedId === id) setSelectedId(null)
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'org'))
    } finally {
      setBusy(false)
    }
  }

  const onMove = async () => {
    if (!selectedId) return
    setBusy(true)
    try {
      await moveOrgUnit(selectedId, moveParent || null)
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'org'))
    } finally {
      setBusy(false)
    }
  }

  const onAssign = async () => {
    if (!selectedId || !memberUser.trim()) return
    setBusy(true)
    try {
      await upsertMembership({
        user_id: memberUser.trim(),
        org_unit_id: selectedId,
        is_primary: true,
        business_roles: [memberRole],
      })
      setMemberUser('')
      const rows = await fetchUnitMemberships(selectedId)
      setMembers(rows)
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'org'))
    } finally {
      setBusy(false)
    }
  }

  const onRemoveMember = async (mid: string) => {
    setBusy(true)
    try {
      await deleteMembership(mid)
      if (selectedId) {
        setMembers(await fetchUnitMemberships(selectedId))
      }
    } catch (e) {
      setErr(formatApiError(e, 'org'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <ForbiddenBanner />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">组织</h1>
          <p className="text-muted-foreground text-sm">
            部门树与成员 / 业务角色（member · dept_manager）
          </p>
        </div>
        <div className="flex items-center gap-2">
          {canWrite ? (
            <label className="text-muted-foreground flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={includeDeleted}
                onChange={(e) => setIncludeDeleted(e.target.checked)}
              />
              显示已归档
            </label>
          ) : null}
          <Button type="button" variant="outline" size="sm" onClick={() => void load()} disabled={busy}>
            刷新
          </Button>
        </div>
      </div>

      {err ? (
        <p className="text-destructive text-sm" role="alert">
          {err}
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">部门树</CardTitle>
            <CardDescription>按 path 缩进；点击选中后管理成员</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {sorted.length === 0 && !busy ? (
              <p className="text-muted-foreground text-sm">暂无部门 — 请先创建根部门</p>
            ) : (
              <ul className="max-h-80 space-y-1 overflow-auto text-sm">
                {sorted.map((u) => (
                  <li key={u.id}>
                    <button
                      type="button"
                      className={`w-full rounded-md px-2 py-1.5 text-left hover:bg-muted ${
                        selectedId === u.id ? 'bg-accent text-accent-foreground' : ''
                      }`}
                      style={{ paddingLeft: `${8 + depthOf(u.path) * 12}px` }}
                      onClick={() => setSelectedId(u.id)}
                    >
                      {u.name}
                      {u.deleted_at ? (
                        <span className="text-muted-foreground ml-2 text-xs">已归档</span>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {canWrite ? (
              <div className="space-y-2 border-t border-border pt-3">
                <Label>新建部门</Label>
                <Input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="名称"
                />
                <Select value={newParent || '__root__'} onValueChange={(v) => setNewParent(v === '__root__' ? '' : v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="父部门（空=根）" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__root__">（根）</SelectItem>
                    {sorted
                      .filter((u) => !u.deleted_at)
                      .map((u) => (
                        <SelectItem key={u.id} value={u.id}>
                          {u.name}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                <Button type="button" onClick={() => void onCreate()} disabled={busy}>
                  创建
                </Button>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">成员</CardTitle>
            <CardDescription>
              {selectedId
                ? `部门 ${sorted.find((u) => u.id === selectedId)?.name ?? selectedId}`
                : '先选择左侧部门'}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {!selectedId ? (
              <p className="text-muted-foreground text-sm">未选择部门</p>
            ) : (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>用户</TableHead>
                      <TableHead>角色</TableHead>
                      <TableHead>主部门</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {members.map((m) => (
                      <TableRow key={m.id}>
                        <TableCell>{m.user_id}</TableCell>
                        <TableCell>{m.business_roles.join(', ')}</TableCell>
                        <TableCell>{m.is_primary ? '是' : ''}</TableCell>
                        <TableCell>
                          {canWrite ? (
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={() => void onRemoveMember(m.id)}
                            >
                              移除
                            </Button>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                {canWrite ? (
                  <div className="space-y-2 border-t border-border pt-3">
                    <Label>分配成员</Label>
                    <Input
                      value={memberUser}
                      onChange={(e) => setMemberUser(e.target.value)}
                      placeholder="user_id"
                    />
                    <Select value={memberRole} onValueChange={setMemberRole}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="member">member</SelectItem>
                        <SelectItem value="dept_manager">dept_manager</SelectItem>
                      </SelectContent>
                    </Select>
                    <Button type="button" onClick={() => void onAssign()} disabled={busy}>
                      设为主部门并授角色
                    </Button>

                    <Label className="pt-2">移父</Label>
                    <Select
                      value={moveParent || '__root__'}
                      onValueChange={(v) => setMoveParent(v === '__root__' ? '' : v)}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="新父部门" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__root__">（根）</SelectItem>
                        {sorted
                          .filter((u) => u.id !== selectedId && !u.deleted_at)
                          .map((u) => (
                            <SelectItem key={u.id} value={u.id}>
                              {u.name}
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                    <div className="flex gap-2">
                      <Button type="button" variant="outline" onClick={() => void onMove()} disabled={busy}>
                        移动
                      </Button>
                      <Button
                        type="button"
                        variant="destructive"
                        onClick={() => void onArchive(selectedId)}
                        disabled={busy}
                      >
                        归档
                      </Button>
                    </div>
                  </div>
                ) : null}
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">我的 memberships</CardTitle>
          <CardDescription>当前登录用户可见范围</CardDescription>
        </CardHeader>
        <CardContent>
          {mine.length === 0 ? (
            <p className="text-muted-foreground text-sm">尚无组织归属</p>
          ) : (
            <ul className="text-sm">
              {mine.map((m) => (
                <li key={m.id}>
                  {m.org_unit_id} · {m.business_roles.join(', ')}
                  {m.is_primary ? ' · 主部门' : ''}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
