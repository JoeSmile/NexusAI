/** Wave S 产品路径与旧 /panels/* 兼容映射 */

export const HOME_PATH = '/workspace/chat'

/** 旧书签 → 新产品路径 */
export const PANEL_REDIRECTS: Record<string, string> = {
  '/panels/chat': '/workspace/chat',
  '/panels/agent': '/workspace/agent',
  '/panels/eval': '/workspace/eval',
  '/panels/rag': '/knowledge',
  '/panels/admin': '/governance/keys',
  '/panels/audit': '/governance/audit',
  '/panels/capabilities': '/governance/capabilities',
  '/panels/performance': '/governance/performance',
}

export function resolvePostLoginPath(next: string | null): string {
  if (!next || !next.startsWith('/')) return HOME_PATH
  return PANEL_REDIRECTS[next] ?? next
}
