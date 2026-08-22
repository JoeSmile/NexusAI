/**
 * Task 63 slice 4 — client-side input guardrails (experience only; backend remains authoritative).
 * Align max length with backend PIPELINE_MAX_INPUT_CHARS default (10000).
 */

export const CHAT_MAX_INPUT_CHARS = 10_000

export type InputValidationResult =
  | { ok: true }
  | { ok: false; reason: 'empty' | 'length'; message: string }

export type SensitiveKind = 'id_card' | 'phone' | 'email' | 'api_key'

export type SensitiveFinding = {
  kind: SensitiveKind
  label: string
}

const SENSITIVE_RULES: { kind: SensitiveKind; label: string; pattern: RegExp }[] = [
  { kind: 'id_card', label: '身份证号', pattern: /\d{17}[\dXx]/ },
  { kind: 'phone', label: '手机号', pattern: /1[3-9]\d{9}/ },
  {
    kind: 'api_key',
    label: '疑似密钥',
    pattern:
      /(?:sk-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----)/,
  },
  {
    kind: 'email',
    label: '邮箱',
    pattern: /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/,
  },
]

const MASK_RULES: { pattern: RegExp; replacement: string }[] = [
  { pattern: /\d{17}[\dXx]/g, replacement: '******************' },
  { pattern: /\d{16,19}/g, replacement: '**** **** **** ****' },
  { pattern: /1[3-9]\d{9}/g, replacement: '1**********' },
  {
    pattern: /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g,
    replacement: '***@***.***',
  },
  { pattern: /sk-[a-zA-Z0-9]{8,}/g, replacement: 'sk-********' },
  { pattern: /AKIA[0-9A-Z]{16}/g, replacement: 'AKIA********' },
]

export function validateChatInput(text: string): InputValidationResult {
  if (!text.trim()) {
    return { ok: false, reason: 'empty', message: '请输入消息内容（不能只发空白）' }
  }
  if (text.length > CHAT_MAX_INPUT_CHARS) {
    return {
      ok: false,
      reason: 'length',
      message: `消息过长（${text.length}/${CHAT_MAX_INPUT_CHARS} 字），请缩短后再发送`,
    }
  }
  return { ok: true }
}

export function detectSensitiveHints(text: string): SensitiveFinding[] {
  if (!text.trim()) return []
  const found: SensitiveFinding[] = []
  const seen = new Set<SensitiveKind>()
  for (const rule of SENSITIVE_RULES) {
    if (seen.has(rule.kind)) continue
    if (rule.pattern.test(text)) {
      found.push({ kind: rule.kind, label: rule.label })
      seen.add(rule.kind)
    }
    rule.pattern.lastIndex = 0
  }
  return found
}

export function maskSensitivePreview(text: string): string {
  let out = text
  for (const { pattern, replacement } of MASK_RULES) {
    out = out.replace(pattern, replacement)
  }
  return out
}

export function inputLengthHint(length: number): string {
  return `${length.toLocaleString()} / ${CHAT_MAX_INPUT_CHARS.toLocaleString()}`
}

export function isNearInputLimit(length: number): boolean {
  return length > CHAT_MAX_INPUT_CHARS * 0.85
}

export function isOverInputLimit(length: number): boolean {
  return length > CHAT_MAX_INPUT_CHARS
}
