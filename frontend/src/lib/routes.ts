/** Frontend route constants — AgentUI product shell */

export const HOME_PATH = '/workspace'

/** Legacy bookmarks → current shell */
export const PANEL_REDIRECTS: Record<string, string> = {
  '/panels/chat': '/workspace',
  '/panels/agent': '/admin',
  '/panels/eval': '/admin',
  '/panels/rag': '/workspace/knowledge',
  '/panels/admin': '/admin/keys',
  '/panels/audit': '/admin/audit',
  '/panels/capabilities': '/admin/capabilities',
  '/panels/performance': '/admin/performance',
  '/knowledge': '/workspace/knowledge',
  '/workflows': '/admin/workflows',
  '/governance/org': '/admin/org',
  '/governance/audit': '/admin/audit',
  '/governance/capabilities': '/admin/capabilities',
  '/governance/performance': '/admin/performance',
  '/governance/keys': '/admin/keys',
}

export function resolvePostLoginPath(next: string | null): string {
  if (!next || !next.startsWith('/')) return HOME_PATH
  return PANEL_REDIRECTS[next] ?? next
}
