/**
 * In-place script generation via POST /api/content/scripts/generate.
 */
import { generateScript } from '@/api/contentOps'
import type { ScriptGenFormValues } from '@/components/agent/ScriptGenDialog'

export type ScriptProgressHandlers = {
  onProgress: (text: string) => void
  onDone: (payload: {
    script: string
    styleIsDefault?: boolean
    artifactId?: string
  }) => void
  onError: (message: string) => void
  form: ScriptGenFormValues
}

export async function runScriptGenInPlace(
  handlers: ScriptProgressHandlers,
): Promise<void> {
  const { onProgress, onDone, onError, form } = handlers
  try {
    onProgress('⏳ 正在按主讲风格生成口播稿…')
    // eslint-disable-next-line no-console -- QA: inspect script.gen context
    console.log('[script.gen] request context', {
      creator_id: form.creator_id,
      duration_sec: form.duration_sec,
      hotspots: form.hotspots,
      extra_instruction: form.extra_instruction,
    })
    const r = await generateScript({
      creator_id: form.creator_id,
      hotspots: form.hotspots,
      duration_sec: form.duration_sec,
      extra_instruction: form.extra_instruction,
      save: true,
    })
    // eslint-disable-next-line no-console -- QA: inspect script.gen response
    console.log('[script.gen] response', {
      style_is_default: r.style_is_default,
      artifact_id: r.artifact_id,
      script_len: (r.script || '').length,
      script_preview: (r.script || '').slice(0, 240),
    })
    const script = (r.script || '').trim()
    if (!script) {
      onError('生成结果为空')
      return
    }
    onDone({
      script,
      styleIsDefault: r.style_is_default,
      artifactId: r.artifact_id,
    })
  } catch (e) {
    onError(e instanceof Error ? e.message : String(e))
  }
}
