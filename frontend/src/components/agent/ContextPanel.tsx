/**
 * AgentUI — 上下文与配置（画像 / RAG / 模型）.
 * Overlay drawer — does not squeeze chat. Separate from BookmarksDrawer.
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { listAvailableModels, type AvailableModelItem } from '@/api/llm'
import { getOrgProfile, putOrgProfile } from '@/api/contentOps'
import { formatApiError } from '@/api/http'
import { ragStatus } from '@/api/rag'
import { RightDrawer } from '@/components/agent/RightDrawer'
import { useChatPrefsStore } from '@/stores/chatPrefsStore'
import { cn } from '@/lib/utils'

type SectionKey = 'profile' | 'rag' | 'model'

export function ContextPanel({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [sections, setSections] = useState<Record<SectionKey, boolean>>({
    profile: true,
    rag: true,
    model: true,
  })
  const [orgName, setOrgName] = useState('')
  const [orgFocus, setOrgFocus] = useState('')
  const [orgAudience, setOrgAudience] = useState('')
  const [orgIndustry, setOrgIndustry] = useState('')
  const [docCount, setDocCount] = useState<number | null>(null)
  const [ragHint, setRagHint] = useState('')
  const [models, setModels] = useState<AvailableModelItem[]>([])
  const [modelsLoaded, setModelsLoaded] = useState(false)
  const [hint, setHint] = useState('')
  const [saving, setSaving] = useState(false)

  const modelId = useChatPrefsStore((s) => s.modelId)
  const temperature = useChatPrefsStore((s) => s.temperature)
  const setModelId = useChatPrefsStore((s) => s.setModelId)
  const setTemperature = useChatPrefsStore((s) => s.setTemperature)

  const toggle = (k: SectionKey) =>
    setSections((s) => ({ ...s, [k]: !s[k] }))

  const refresh = useCallback(async () => {
    setHint('')
    setModelsLoaded(false)
    try {
      const [profile, rag, available] = await Promise.all([
        getOrgProfile().catch(() => ({ profile: {} })),
        ragStatus().catch(() => null),
        listAvailableModels().catch(() => ({ items: [] })),
      ])
      const p = profile.profile || {}
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
      const current = useChatPrefsStore.getState().modelId
      if (!current && items[0]?.model) {
        setModelId(items[0].model)
      } else if (current && items.length > 0 && !items.some((m) => m.model === current)) {
        setModelId(items[0].model)
      }
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

  const configured = Boolean(orgName || orgFocus)

  return (
    <RightDrawer open={open} title="上下文与配置" onClose={onClose}>
      {hint ? (
        <div style={{ fontSize: 12, color: 'var(--color-gray-500)', padding: '0 4px 8px' }}>
          {hint}
        </div>
      ) : null}

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
              <Link
                to="/admin/keys"
                className="btn-primary btn-sm"
                style={{ alignSelf: 'flex-start' }}
              >
                配置 LLM
              </Link>
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
                    默认 0.3；不限制 max tokens（走模型默认）。
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
