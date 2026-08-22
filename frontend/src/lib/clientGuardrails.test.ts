import { describe, expect, it } from 'vitest'

import {
  CHAT_MAX_INPUT_CHARS,
  detectSensitiveHints,
  maskSensitivePreview,
  validateChatInput,
} from '@/lib/clientGuardrails'

describe('clientGuardrails', () => {
  it('rejects empty and whitespace-only', () => {
    expect(validateChatInput('').ok).toBe(false)
    expect(validateChatInput('   \n\t').ok).toBe(false)
  })

  it('rejects over max length without truncating', () => {
    const long = 'a'.repeat(CHAT_MAX_INPUT_CHARS + 1)
    const res = validateChatInput(long)
    expect(res.ok).toBe(false)
    if (!res.ok) expect(res.reason).toBe('length')
  })

  it('detects phone and id card hints', () => {
    const findings = detectSensitiveHints('联系我 13800138000 或身份证 110101199001011234')
    expect(findings.some((f) => f.kind === 'phone')).toBe(true)
    expect(findings.some((f) => f.kind === 'id_card')).toBe(true)
  })

  it('masks sensitive preview', () => {
    const masked = maskSensitivePreview('tel 13800138000')
    expect(masked).not.toContain('13800138000')
    expect(masked).toContain('1**********')
  })
})
