import type { AvailableModelItem } from '@/api/llm'

/** Sync client model pick with tenant-configured chat models. */
export function pickDefaultModelId(
  items: AvailableModelItem[],
  current: string,
): string {
  const names = items.map((i) => i.model).filter(Boolean)
  if (names.length === 0) return ''
  if (names.length === 1) return names[0]
  if (current && names.includes(current)) return current
  return names[0]
}

export function canConfigureTenantLlm(role: string): boolean {
  return role === 'tenant_admin' || role === 'super_admin'
}
