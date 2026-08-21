/** 47b 差评理由（暂定 6 项；可多选 + 自由补充）。 */
export const DISLIKE_REASONS = [
  { id: 'off_topic', label: '答非所问' },
  { id: 'factual_error', label: '事实不准' },
  { id: 'too_long', label: '太长太啰嗦' },
  { id: 'too_thin', label: '信息不够' },
  { id: 'wrong_style', label: '风格不对' },
  { id: 'unsafe', label: '有风险或不安全' },
] as const

export type DislikeReasonId = (typeof DISLIKE_REASONS)[number]['id']

export function formatDislikeComment(
  reasonIds: readonly string[],
  note: string,
): string {
  const labels = DISLIKE_REASONS.filter((r) => reasonIds.includes(r.id)).map(
    (r) => r.label,
  )
  const n = note.trim().slice(0, 500)
  const parts: string[] = []
  if (labels.length) parts.push(labels.join('；'))
  if (n) parts.push(`补充：${n}`)
  return parts.join(' | ')
}
