/**
 * Admin · 模型凭证（行业标准：备注名 + Key + 模型名 + Base URL）
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ClipboardEvent,
} from 'react'

import {
  createLlmKey,
  deactivateLlmKey,
  deleteLlmKey,
  listLlmKeys,
  patchLlmKey,
  type LlmKeyPurpose,
  type LlmKeyRow,
} from '@/api/admin'
import { formatApiError } from '@/api/http'
import { EMBEDDING_DIMENSIONS, API_KEY_EDIT_PLACEHOLDER, maskApiKeyPreview } from '@/api/llm'
import { ForbiddenBanner } from '@/components/role/RoleSwitcher'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
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
import { useForbiddenStore } from '@/stores/forbiddenStore'

type FormMode = 'create' | 'edit'

type CredentialFormState = {
  purpose: LlmKeyPurpose
  alias: string
  model: string
  baseUrl: string
}

function purposeLabel(p: string | undefined): string {
  return p === 'embedding' ? 'Embedding' : '对话'
}

function rowPurpose(row: LlmKeyRow): LlmKeyPurpose {
  const raw = (row.purpose || row.provider || 'chat').toLowerCase()
  return raw === 'embedding' ? 'embedding' : 'chat'
}

function rowModel(row: LlmKeyRow): string {
  if (row.model?.trim()) return row.model.trim()
  const first = (row.allowed_models ?? []).find((m) => m?.trim())
  return first?.trim() ?? ''
}

export default function AdminPanel() {
  const role = useAuthStore((s) => s.activeRole)
  const roleEpoch = useAuthStore((s) => s.roleEpoch)
  const [llmKeys, setLlmKeys] = useState<LlmKeyRow[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const [dialogOpen, setDialogOpen] = useState(false)
  const [formMode, setFormMode] = useState<FormMode>('create')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingIsActive, setEditingIsActive] = useState(true)
  const [form, setForm] = useState<CredentialFormState>({
    purpose: 'chat',
    alias: '',
    model: '',
    baseUrl: '',
  })

  const apiKeySecretRef = useRef('')
  const [apiKeyMasked, setApiKeyMasked] = useState('')

  const clearApiKeyField = () => {
    apiKeySecretRef.current = ''
    setApiKeyMasked('')
  }

  const onApiKeyPaste = (e: ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault()
    const raw = e.clipboardData.getData('text').trim()
    if (!raw) return
    apiKeySecretRef.current = raw
    setApiKeyMasked(maskApiKeyPreview(raw))
  }

  const load = useCallback(async () => {
    setErr('')
    try {
      const rows = await listLlmKeys()
      setLlmKeys(rows)
    } catch (e) {
      setLlmKeys([])
      setErr(formatApiError(e, 'admin:llm_key'))
    }
  }, [])

  useEffect(() => {
    useForbiddenStore.getState().clear()
    void load()
  }, [roleEpoch, role, load])

  const openCreate = (purpose: LlmKeyPurpose) => {
    setFormMode('create')
    setEditingId(null)
    setEditingIsActive(true)
    setForm({
      purpose,
      alias: purpose === 'chat' ? '公司对话模型' : '公司 Embedding',
      model: '',
      baseUrl: '',
    })
    clearApiKeyField()
    setErr('')
    setDialogOpen(true)
  }

  const openEdit = (row: LlmKeyRow) => {
    setFormMode('edit')
    setEditingId(row.id)
    setEditingIsActive(row.is_active !== false)
    setForm({
      purpose: rowPurpose(row),
      alias: row.key_alias ?? '',
      model: rowModel(row),
      baseUrl: row.base_url ?? '',
    })
    clearApiKeyField()
    setErr('')
    setDialogOpen(true)
  }

  const closeDialog = () => {
    setDialogOpen(false)
    clearApiKeyField()
  }

  const onSubmit = async () => {
    setBusy(true)
    setErr('')
    try {
      if (!form.alias.trim()) throw new Error('请填写备注名')
      if (!form.model.trim()) throw new Error('请填写模型名称')
      if (!form.baseUrl.trim()) throw new Error('请填写 Base URL')

      if (formMode === 'create') {
        const secret = apiKeySecretRef.current.trim()
        if (!secret) throw new Error('请粘贴 API Key（粘贴后仅显示前后各 6 位）')
        await createLlmKey({
          key_alias: form.alias.trim(),
          provider: form.purpose,
          api_key_plaintext: secret,
          model: form.model.trim(),
          base_url: form.baseUrl.trim(),
        })
      } else if (editingId != null) {
        const body: Parameters<typeof patchLlmKey>[1] = {
          key_alias: form.alias.trim(),
          model: form.model.trim(),
          base_url: form.baseUrl.trim(),
        }
        const secret = apiKeySecretRef.current.trim()
        if (secret) body.api_key_plaintext = secret
        await patchLlmKey(editingId, body)
      }
      closeDialog()
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'admin:llm_key'))
    } finally {
      setBusy(false)
    }
  }

  const onDeactivate = async (row: LlmKeyRow) => {
    const model = rowModel(row) || row.key_alias
    const ok = window.confirm(
      `确认停用「${row.key_alias}」？\n停用后模型「${model}」将不可再用于${purposeLabel(rowPurpose(row))}。`,
    )
    if (!ok) return
    setBusy(true)
    setErr('')
    try {
      await deactivateLlmKey(row.id)
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'admin:llm_key'))
    } finally {
      setBusy(false)
    }
  }

  const onDeleteFromDialog = async () => {
    if (editingId == null) return
    const ok = window.confirm(
      `确认永久删除「${form.alias.trim() || '该凭证'}」？\n删除后 API Key 将从系统中彻底清除，且无法恢复。`,
    )
    if (!ok) return
    setBusy(true)
    setErr('')
    try {
      await deleteLlmKey(editingId)
      closeDialog()
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'admin:llm_key'))
    } finally {
      setBusy(false)
    }
  }

  const onReactivate = async () => {
    if (editingId == null) return
    setBusy(true)
    setErr('')
    try {
      await patchLlmKey(editingId, { is_active: true })
      setEditingIsActive(true)
      await load()
    } catch (e) {
      setErr(formatApiError(e, 'admin:llm_key'))
    } finally {
      setBusy(false)
    }
  }

  const dialogTitle =
    formMode === 'edit'
      ? `编辑${purposeLabel(form.purpose)}凭证`
      : form.purpose === 'embedding'
        ? '添加 Embedding 凭证'
        : '添加对话凭证'

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">模型凭证</h1>
          <p className="text-muted-foreground text-xs">
            当前角色 <code>{role}</code>
            。每条凭证填写备注名、API Key、模型名称与 Base URL；对话与 Embedding 分开添加。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" className="min-w-[9.5rem] whitespace-nowrap px-4" onClick={() => openCreate('chat')}>
            添加对话凭证
          </Button>
          <Button type="button" variant="secondary" className="min-w-[11rem] whitespace-nowrap px-4" onClick={() => openCreate('embedding')}>
            添加 Embedding 凭证
          </Button>
          <Button type="button" size="sm" variant="outline" className="whitespace-nowrap px-3" onClick={() => void load()}>
            刷新
          </Button>
        </div>
      </div>

      <ForbiddenBanner />
      {err && !dialogOpen ? (
        <p className="text-destructive text-sm" role="alert">
          {err}
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">已配置凭证</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>备注名</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>模型名称</TableHead>
                <TableHead>API Key</TableHead>
                <TableHead>Base URL</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {llmKeys.map((k) => {
                const purpose = rowPurpose(k)
                const model = rowModel(k)
                return (
                  <TableRow key={String(k.id ?? k.key_alias)}>
                    <TableCell className="font-medium">{k.key_alias ?? '—'}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{purposeLabel(purpose)}</Badge>
                      {purpose === 'embedding' ? (
                        <span className="text-muted-foreground ml-1 text-[10px]">
                          {k.embedding_dimensions ?? EMBEDDING_DIMENSIONS} 维
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      {model ? (
                        <code className="text-xs">{model}</code>
                      ) : (
                        <span className="text-muted-foreground text-xs">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {k.key_preview ? (
                        <code className="text-muted-foreground text-xs">{k.key_preview}</code>
                      ) : (
                        <span className="text-muted-foreground text-xs">—</span>
                      )}
                    </TableCell>
                    <TableCell className="max-w-[220px] truncate text-xs" title={k.base_url}>
                      {k.base_url || '—'}
                    </TableCell>
                    <TableCell>
                      {k.is_active === false ? (
                        <Badge variant="outline">已停用</Badge>
                      ) : (
                        <Badge variant="success">启用中</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          onClick={() => openEdit(k)}
                        >
                          编辑
                        </Button>
                        {k.is_active !== false ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="destructive"
                            disabled={busy}
                            onClick={() => void onDeactivate(k)}
                          >
                            停用
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
          {llmKeys.length === 0 ? (
            <p className="text-muted-foreground mt-2 text-xs">
              尚未添加凭证。点击上方按钮填写。
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          if (!open) closeDialog()
          else setDialogOpen(true)
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{dialogTitle}</DialogTitle>
            <DialogDescription>
              粘贴 Key 后只显示前后各 6 位；完整明文不会写入页面状态。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-1">
            {err && dialogOpen ? (
              <p className="text-destructive text-sm" role="alert">
                {err}
              </p>
            ) : null}

            {formMode === 'edit' && !editingIsActive ? (
              <div className="flex items-center justify-between gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-950">
                <span>当前为已停用，保存不会自动启用。</span>
                <Button
                  type="button"
                  size="sm"
                  disabled={busy}
                  onClick={() => void onReactivate()}
                >
                  重新启用
                </Button>
              </div>
            ) : null}

            <div className="space-y-1">
              <Label htmlFor="cred-alias">备注名</Label>
              <Input
                id="cred-alias"
                value={form.alias}
                onChange={(e) => setForm((f) => ({ ...f, alias: e.target.value }))}
                placeholder="例如：公司对话模型"
              />
              <p className="text-muted-foreground text-xs">
                本租户内的称呼，用来区分多把 Key（须唯一）。
              </p>
            </div>

            <div className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <Label htmlFor="cred-api-key">
                  API Key{formMode === 'edit' ? '（可选，重贴则轮换）' : ''}
                </Label>
                {apiKeyMasked ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2 text-xs"
                    onClick={clearApiKeyField}
                  >
                    清除重贴
                  </Button>
                ) : null}
              </div>
              <Input
                id="cred-api-key"
                autoComplete="off"
                spellCheck={false}
                value={apiKeyMasked}
                readOnly={Boolean(apiKeyMasked)}
                placeholder={
                  formMode === 'edit' ? API_KEY_EDIT_PLACEHOLDER : '在此粘贴 API Key'
                }
                onPaste={onApiKeyPaste}
                onChange={() => {
                  if (!apiKeyMasked) return
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Backspace' || e.key === 'Delete') {
                    e.preventDefault()
                    clearApiKeyField()
                  }
                }}
              />
            </div>

            <div className="space-y-1">
              <Label htmlFor="cred-model">模型名称</Label>
              <Input
                id="cred-model"
                value={form.model}
                onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
                placeholder={
                  form.purpose === 'embedding'
                    ? '例如：text-embedding-3-small'
                    : '例如：deepseek-v4-flash'
                }
              />
            </div>

            <div className="space-y-1">
              <Label htmlFor="cred-base-url">Base URL</Label>
              <Input
                id="cred-base-url"
                value={form.baseUrl}
                onChange={(e) => setForm((f) => ({ ...f, baseUrl: e.target.value }))}
                placeholder="例如：https://api.deepseek.com/v1"
              />
            </div>

            {form.purpose === 'embedding' ? (
              <p className="bg-muted rounded-md px-3 py-2 text-xs">
                向量维度：<strong>{EMBEDDING_DIMENSIONS}</strong>（暂不可改）
              </p>
            ) : null}
          </div>

          <DialogFooter className="sm:justify-between">
            {formMode === 'edit' && editingId != null ? (
              <Button
                type="button"
                variant="destructive"
                disabled={busy}
                onClick={() => void onDeleteFromDialog()}
              >
                删除
              </Button>
            ) : (
              <span />
            )}
            <div className="flex gap-2">
              <Button type="button" variant="outline" disabled={busy} onClick={closeDialog}>
                取消
              </Button>
              <Button type="button" disabled={busy} onClick={() => void onSubmit()}>
                {formMode === 'edit' ? '保存' : '添加'}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
