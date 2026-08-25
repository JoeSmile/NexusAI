/**
 * AgentUI — 记忆面板（画像 / 风格 / 生效记忆 / RAG / 模型）.
 * Overlay drawer — does not squeeze chat. Separate from BookmarksDrawer.
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { listAvailableModels, type AvailableModelItem } from '@/api/llm'
import { getOrgProfile, listStyles, putOrgProfile } from '@/api/contentOps'
import { formatApiError } from '@/api/http'
import {
  deleteMyMemory,
  listMyMemories,
  patchMyMemory,
  type WarmMemory,
} from '@/api/memory'
import { ragStatus } from '@/api/rag'
import { RightDrawer } from '@/components/agent/RightDrawer'
import { canConfigureTenantLlm, pickDefaultModelId } from '@/lib/chatModels'
import { useChatPrefsStore } from '@/stores/chatPrefsStore'
import { useAuthStore } from '@/stores/authStore'
import { cn } from '@/lib/utils'

type SectionKey = 'memory' | 'profile' | 'style' | 'rag' | 'model'

const EMPTY_MEMORY = '暂无记忆,多聊聊自动积累'

function memoryText(m: WarmMemory): string {
  const raw = (m.value || '').trim()
  if (!raw) return m.content || m.key
  try {
    const obj = JSON.parse(raw) as { text?: string }
    if (obj && typeof obj.text === 'string' && obj.text.trim()) return obj.text
  } catch {
    /* plain text */
  }
  return raw
}

/** Keep bookmark JSON envelope (`text` + session_id / user_message) on edit. */
export function memoryPatchPayload(existing: WarmMemory | undefined, text: string): string {
  if (!existing?.value) return text
  try {
    const obj = JSON.parse(existing.value) as Record<string, unknown>
    if (obj && typeof obj === 'object' && typeof obj.text === 'string') {
      return JSON.stringify({ ...obj, text })
    }
  } catch {
    /* plain text */
  }
  return text
}

function sourceLabel(m: WarmMemory): string {
  if (m.key.startsWith('bookmark:') || m.type === 'bookmark') return '收藏'
  if (m.type === 'extracted') return '自动'
  return '手动'
}

export function ContextPanel({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [sections, setSections] = useState<Record<SectionKey, boolean>>({
    memory: true,
    profile: true,
    style: true,
    rag: false,
    model: false,
  })
  const [orgName, setOrgName] = useState('')
  const [orgFocus, setOrgFocus] = useState('')
  const [orgAudience, setOrgAudience] = useState('')
  const [orgIndustry, setOrgIndustry] = useState('')
  const [styleSummary, setStyleSummary] = useState('')
  const [memories, setMemories] = useState<WarmMemory[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [docCount, setDocCount] = useState<number | null>(null)
  const [ragHint, setRagHint] = useState('')
  const [models, setModels] = useState<AvailableModelItem[]>([])
  const [modelsLoaded, setModelsLoaded] = useState(false)
  const [hint, setHint] = useState('')
  const [saving, setSaving] = useState(false)

  const modelId = useChatPrefsStore((s) => s.modelId)
  const temperature = useChatPrefsStore((s) => s.temperature)
  const maxTokens = useChatPrefsStore((s) => s.maxTokens)
  const setModelId = useChatPrefsStore((s) => s.setModelId)
  const setTemperature = useChatPrefsStore((s) => s.setTemperature)
  const setMaxTokens = useChatPrefsStore((s) => s.setMaxTokens)
  const activeRole = useAuthStore((s) => s.activeRole)
  const canConfigureLlm = canConfigureTenantLlm(activeRole)

  const toggle = (k: SectionKey) =>
    setSections((s) => ({ ...s, [k]: !s[k] }))

  const refresh = useCallback(async () => {
    setHint('')
    setModelsLoaded(false)
    try {
      const [profile, rag, available, styleRes, memRes] = await Promise.all([
        getOrgProfile().catch(() => ({ profile: {} as Record<string, string> })),
        ragStatus().catch(() => null),
        listAvailableModels().catch(() => ({ items: [] })),
        listStyles().catch(() => ({ items: [], default_creator_id: 'default' })),
        listMyMemories().catch(() => ({ memories: [] as WarmMemory[], total: 0 })),
      ])
      const p = (profile.profile ?? {}) as Record<string, unknown>
      setOrgName(String(p.name || ''))
      setOrgFocus(String(p.product_focus || p.productFocus || ''))
      setOrgAudience(String(p.target_audience || p.targetAudience || ''))
      setOrgIndustry(String(p.industry || ''))
      const n = rag?.data?.document_count
      setDocCount(typeof n === 'number' ? n : null)
      setRagHint(rag?.data?.status ? String(rag.data.status) : '')
      const items = available.items ?? []
      setModels(items)
      setModelsLoaded(true)
      const nextModel = pickDefaultModelId(
        items,
        useChatPrefsStore.getState().modelId,
      )
      if (nextModel) setModelId(nextModel)
      const styles = styleRes.items ?? []
      const defId = styleRes.default_creator_id
      const st =
        styles.find((s) => s.is_default) ||
        styles.find((s) => s.creator_id === defId) ||
        styles[0]
      if (st) {
        const bits = [st.display_name, st.persona, (st.catchphrases || []).slice(0, 2).join('、')]
        setStyleSummary(bits.filter(Boolean).join(' · ') || '已配置默认风格')
      } else {
        setStyleSummary('未配置主讲风格（生成时用默认口吻）')
      }
      setMemories(
        (memRes.memories ?? []).filter(
          (m) =>
            m.key &&
            m.key !== '__forgotten__' &&
            !m.key.startsWith('pending:') &&
            !m.key.startsWith('bookmark:'),
        ),
      )
      setEditingId(null)
    } catch (e) {
      setModelsLoaded(true)
      setHint(formatApiError(e))
    }
  }, [setModelId])

  useEffect(() => {
    if (!open) return
    void refresh()
  }, [open, refresh])

  const saveProfile = async () => {
    setSaving(true)
    setHint('')
    try {
      await putOrgProfile({
        name: orgName,
        industry: orgIndustry,
        product_focus: orgFocus,
        target_audience: orgAudience,
      })
      setHint('企业画像已保存')
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setSaving(false)
    }
  }

  const saveMemory = async (id: string) => {
    const text = draft.trim()
    if (!text) return
    setSaving(true)
    setHint('')
    try {
      const existing = memories.find((m) => m.id === id)
      await patchMyMemory(id, memoryPatchPayload(existing, text))
      setHint('记忆已更新')
      await refresh()
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setSaving(false)
    }
  }

  const removeMemory = async (id: string) => {
    setSaving(true)
    setHint('')
    try {
      await deleteMyMemory(id)
      setHint('记忆已删除')
      await refresh()
    } catch (e) {
      setHint(formatApiError(e))
    } finally {
      setSaving(false)
    }
  }

  const configured = Boolean(orgName || orgFocus)

  return (
    <RightDrawer open={open} title="记忆面板" onClose={onClose}>
      {hint ? (
        <div style={{ fontSize: 12, color: 'var(--color-gray-500)', padding: '0 4px 8px' }}>
          {hint}
        </div>
      ) : null}

      <div className="collapsible-section">
        <button type="button" className="section-header" onClick={() => toggle('memory')}>
          <div className="section-header-title">生效记忆</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="badge badge-gray">{memories.length} 条</span>
            <span className={cn('section-chevron', sections.memory && 'open')}>›</span>
          </div>
        </button>
        {sections.memory ? (
          <div className="section-body">
            {memories.length === 0 ? (
              <p className="bookmarks-hint">{EMPTY_MEMORY}</p>
            ) : (
              <ul className="memory-list">
                {memories.map((m) => (
                  <li key={m.id} className="memory-row">
                    <div className="memory-row-head">
                      <span className="badge badge-gray">{sourceLabel(m)}</span>
                      <span className="memory-key">{m.key}</span>
                    </div>
                    {editingId === m.id ? (
                      <>
                        <textarea
                          className="select-field"
                          rows={3}
                          value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                        />
                        <div className="memory-actions">
                          <button
                            type="button"
                            className="btn-primary btn-sm"
                            disabled={saving}
                            onClick={() => void saveMemory(m.id)}
                          >
                            保存
                          </button>
                          <button
                            type="button"
                            className="btn-secondary btn-sm"
                            onClick={() => setEditingId(null)}
                          >
                            取消
                          </button>
                        </div>
                      </>
                    ) : (
                      <>
                        <p className="memory-text">{memoryText(m)}</p>
                        <div className="memory-actions">
                          <button
                            type="button"
                            className="btn-secondary btn-sm"
                            disabled={saving}
                            onClick={() => {
                              setEditingId(m.id)
                              setDraft(memoryText(m))
                            }}
                          >
                            编辑
                          </button>
                          <button
                            type="button"
                            className="btn-secondary btn-sm"
                            disabled={saving}
                            onClick={() => void removeMemory(m.id)}
                          >
                            删除
                          </button>
                        </div>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="bookmarks-hint">
              收藏请用顶栏「收藏」管理；暂不写入对话记忆、也不注入生成。
            </p>
          </div>
        ) : null}
      </div>

      <div className="collapsible-section">
        <button type="button" className="section-header" onClick={() => toggle('style')}>
          <div className="section-header-title">风格摘要</div>
          <span className={cn('section-chevron', sections.style && 'open')}>›</span>
        </button>
        {sections.style ? (
          <div className="section-body">
            <p style={{ fontSize: 12, color: 'var(--color-gray-600)', margin: 0 }}>
              {styleSummary || '加载中…'}
            </p>
            <Link
              to="/workspace/content"
              style={{ fontSize: 12, color: 'var(--color-primary-600)' }}
            >
              去内容运营管理主讲风格 →
            </Link>
          </div>
        ) : null}
      </div>

      <div className="collapsible-section">
        <button type="button" className="section-header" onClick={() => toggle('profile')}>
          <div className="section-header-title">企业画像</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {configured ? (
              <span className="badge badge-success">已配置</span>
            ) : (
              <span className="badge badge-gray">可填写</span>
            )}
            <span className={cn('section-chevron', sections.profile && 'open')}>›</span>
          </div>
        </button>
        {sections.profile ? (
          <div className="section-body">
            <label className="form-label">企业名称</label>
            <input
              className="select-field"
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              placeholder="请填写"
            />
            <label className="form-label">所属行业</label>
            <input
              className="select-field"
              value={orgIndustry}
              onChange={(e) => setOrgIndustry(e.target.value)}
              placeholder="请填写"
            />
            <label className="form-label">产品方向</label>
            <textarea
              className="select-field"
              rows={2}
              value={orgFocus}
              onChange={(e) => setOrgFocus(e.target.value)}
              placeholder="请填写"
            />
            <label className="form-label">目标人群</label>
            <input
              className="select-field"
              value={orgAudience}
              onChange={(e) => setOrgAudience(e.target.value)}
              placeholder="请填写"
            />
            <button
              type="button"
              className="btn-secondary btn-sm"
              style={{ alignSelf: 'flex-start' }}
              disabled={saving}
              onClick={() => void saveProfile()}
            >
              {saving ? '保存中…' : '保存企业画像'}
            </button>
            <Link
              to="/workspace/content"
              style={{ fontSize: 12, color: 'var(--color-primary-600)' }}
            >
              内容运营里还可配主讲风格 →
            </Link>
          </div>
        ) : null}
      </div>

      <div className="collapsible-section">
        <button type="button" className="section-header" onClick={() => toggle('rag')}>
          <div className="section-header-title">RAG 语料</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="badge badge-gray">
              {docCount == null ? '—' : `${docCount} 文档`}
            </span>
            <span className={cn('section-chevron', sections.rag && 'open')}>›</span>
          </div>
        </button>
        {sections.rag ? (
          <div className="section-body">
            <div className="info-row">
              <span className="info-label">状态</span>
              <span className="info-value">{ragHint || '未知'}</span>
            </div>
            <p style={{ fontSize: 12, color: 'var(--color-gray-500)', margin: 0 }}>
              公司资料走知识库 RAG；主讲风格上传在内容运营（与语料分离）。
            </p>
            <Link to="/workspace/knowledge" className="btn-primary btn-sm" style={{ alignSelf: 'flex-start' }}>
              管理 / 上传文档
            </Link>
          </div>
        ) : null}
      </div>

      <div className="collapsible-section">
        <button type="button" className="section-header" onClick={() => toggle('model')}>
          <div className="section-header-title">模型设置</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {modelsLoaded ? (
              <span className={models.length > 0 ? 'badge badge-success' : 'badge badge-gray'}>
                {models.length > 0 ? '已配置' : '未配置'}
              </span>
            ) : null}
            <span className={cn('section-chevron', sections.model && 'open')}>›</span>
          </div>
        </button>
        {sections.model ? (
          <div className="section-body">
            {!modelsLoaded ? (
              <p style={{ fontSize: 12, color: 'var(--color-gray-500)', margin: 0 }}>
                加载中…
              </p>
            ) : models.length === 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <p style={{ fontSize: 12, color: 'var(--color-gray-500)', margin: 0 }}>
                  {canConfigureLlm
                    ? '尚未配置对话模型凭证，请添加后再使用。'
                    : '租户管理员尚未配置对话模型，请联系管理员后再使用。'}
                </p>
                {canConfigureLlm ? (
                  <Link
                    to="/admin/keys"
                    className="btn-primary btn-sm"
                    style={{ alignSelf: 'flex-start' }}
                  >
                    配置 LLM
                  </Link>
                ) : null}
              </div>
            ) : models.length === 1 ? (
              <>
                <div className="info-row">
                  <span className="info-label">当前模型</span>
                  <span className="info-value">
                    <code>{models[0].model}</code>
                    <span className="text-muted-foreground ml-1 text-[10px]">
                      （租户统一配置）
                    </span>
                  </span>
                </div>
                <div className="slider-wrap">
                  <div className="slider-label">
                    <span>Temperature</span>
                    <span className="slider-value">{temperature.toFixed(1)}</span>
                  </div>
                  <input
                    type="range"
                    className="slider"
                    min={0}
                    max={1}
                    step={0.1}
                    value={temperature}
                    onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  />
                </div>
                <div className="slider-wrap">
                  <div className="slider-label">
                    <span>Max tokens</span>
                    <span className="slider-value">
                      {maxTokens > 0 ? String(maxTokens) : '模型默认'}
                    </span>
                  </div>
                  <input
                    type="range"
                    className="slider"
                    min={0}
                    max={4096}
                    step={256}
                    value={maxTokens}
                    onChange={(e) => setMaxTokens(parseInt(e.target.value, 10))}
                  />
                </div>
              </>
            ) : (
              <>
                <div className="form-group">
                  <label className="form-label">当前模型</label>
                  <select
                    className="select-field"
                    value={modelId}
                    onChange={(e) => setModelId(e.target.value)}
                  >
                    {models.map((m) => (
                      <option key={m.model} value={m.model}>
                        {m.model}
                        {m.series ? ` · ${m.series}` : ''}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="slider-wrap">
                  <div className="slider-label">
                    <span>Temperature</span>
                    <span className="slider-value">{temperature.toFixed(1)}</span>
                  </div>
                  <input
                    type="range"
                    className="slider"
                    min={0}
                    max={1}
                    step={0.1}
                    value={temperature}
                    onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  />
                  <div style={{ fontSize: 11, color: 'var(--color-gray-400)' }}>
                    默认 0.3，会随每次对话请求发给模型。
                  </div>
                </div>
                <div className="slider-wrap">
                  <div className="slider-label">
                    <span>Max tokens</span>
                    <span className="slider-value">
                      {maxTokens > 0 ? String(maxTokens) : '模型默认'}
                    </span>
                  </div>
                  <input
                    type="range"
                    className="slider"
                    min={0}
                    max={4096}
                    step={256}
                    value={maxTokens}
                    onChange={(e) => setMaxTokens(parseInt(e.target.value, 10))}
                  />
                  <div style={{ fontSize: 11, color: 'var(--color-gray-400)' }}>
                    0 = 不传 max_tokens，交给模型默认上限。
                  </div>
                </div>
              </>
            )}
          </div>
        ) : null}
      </div>
    </RightDrawer>
  )
}
