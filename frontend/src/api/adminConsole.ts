import { apiGet, apiPatch, apiPut, apiPost, apiDelete } from '@/api/http'

export type ExecPolicy = {
  timeout_s: number
  hard_kill_timeout_s: number
  max_retries: number
  rate_limit_per_min: number
  isolation_mode: string
  max_payload_bytes: number
  max_concurrent_mcp_subprocess: number
}

export type ConsoleToolSummary = {
  id: string
  name: string
  kind: string
  provider: string
  status: string
  permission?: string
  tenant_id?: string
  risk_level: string
  supply_origin: string
  domain: string
  executor: string
  requires_approval: boolean
  tenant_allowlist: string[]
  description: string
  exec_policy: ExecPolicy
}

export type ConsoleToolDetail = ConsoleToolSummary & {
  spec: Record<string, unknown>
  tool_contract: Record<string, unknown>
  param_spec: Record<string, unknown> | null
  cost_model: Record<string, unknown>
}

export type ConsoleToolListResponse = {
  items: ConsoleToolSummary[]
  total: number
}

export async function listConsoleTools(opts?: {
  q?: string
  risk?: string
  source?: string
  status?: string
  domain?: string
  include_disabled?: boolean
}) {
  const p = new URLSearchParams()
  if (opts?.q) p.set('q', opts.q)
  if (opts?.risk) p.set('risk', opts.risk)
  if (opts?.source) p.set('source', opts.source)
  if (opts?.status) p.set('status', opts.status)
  if (opts?.domain) p.set('domain', opts.domain)
  if (opts?.include_disabled === false) p.set('include_disabled', 'false')
  const qs = p.toString()
  return apiGet<ConsoleToolListResponse>(`/api/admin/console/tools${qs ? `?${qs}` : ''}`)
}

export async function getConsoleTool(capabilityId: string) {
  return apiGet<ConsoleToolDetail>(
    `/api/admin/console/tools/${encodeURIComponent(capabilityId)}`,
  )
}

export async function patchConsoleToolStatus(capabilityId: string, status: 'enabled' | 'disabled') {
  return apiPatch<{ ok: boolean; item: ConsoleToolSummary }>(
    `/api/admin/console/tools/${encodeURIComponent(capabilityId)}/status`,
    { status },
  )
}

export async function putConsoleToolTenantAllowlist(
  capabilityId: string,
  tenantIds: string[],
) {
  return apiPut<{ ok: boolean; tenant_allowlist: string[]; item: ConsoleToolSummary }>(
    `/api/admin/console/tools/${encodeURIComponent(capabilityId)}/tenant-allowlist`,
    { tenant_ids: tenantIds },
  )
}

export async function putConsoleToolExecPolicy(
  capabilityId: string,
  patch: Partial<ExecPolicy>,
) {
  return apiPut<{ ok: boolean; exec_policy: ExecPolicy; item: ConsoleToolSummary }>(
    `/api/admin/console/tools/${encodeURIComponent(capabilityId)}/exec-policy`,
    patch,
  )
}

export async function getConsoleHealth() {
  return apiGet<{ ok: boolean; role: string; super_admin: boolean; tenant_id: string }>(
    '/api/admin/console/health',
  )
}

export type McpServerItem = {
  id: string
  tenant_id: string
  transport: string
  command: string
  args: string[]
  env: Record<string, string>
  url: string
  headers: Record<string, string>
  header_keys: string[]
  enabled: boolean
  allow_pass_user_context: boolean
  timeout_s: number
  last_probe: Record<string, unknown>
  source: string
  display_status: string
  runtime: { circuit_state: string; connection_status: string }
}

export type McpToolPreview = {
  name: string
  description: string
  property_count: number
  input_schema_type: string
}

export async function listMcpServers() {
  return apiGet<{ items: McpServerItem[]; total: number }>('/api/admin/console/mcp/servers')
}

export async function createMcpServer(body: Partial<McpServerItem> & { id: string }) {
  return apiPost<{ ok: boolean; item: McpServerItem }>('/api/admin/console/mcp/servers', body)
}

export async function updateMcpServer(serverId: string, body: Partial<McpServerItem>) {
  return apiPut<{ ok: boolean; item: McpServerItem }>(
    `/api/admin/console/mcp/servers/${encodeURIComponent(serverId)}`,
    body,
  )
}

export async function deleteMcpServer(serverId: string) {
  return apiDelete<{ ok: boolean; id: string }>(
    `/api/admin/console/mcp/servers/${encodeURIComponent(serverId)}`,
  )
}

export async function testMcpServer(serverId: string) {
  return apiPost<{
    ok: boolean
    status: string
    tool_count?: number
    tools?: McpToolPreview[]
    error?: Record<string, unknown>
    runtime: McpServerItem['runtime']
  }>(`/api/admin/console/mcp/servers/${encodeURIComponent(serverId)}/test`, {})
}

export async function importMcpTools(
  serverId: string,
  body: { tool_names: string[]; risk_overrides?: Record<string, string> },
) {
  return apiPost<{
    ok: boolean
    registered: Array<Record<string, unknown>>
    rejected: Array<Record<string, unknown>>
  }>(`/api/admin/console/mcp/servers/${encodeURIComponent(serverId)}/import-tools`, body)
}

export type SkillUsage = {
  uses: number
  successes: number
  avg_tokens: number
  hit_rate: number
  required_permissions: string[]
}

export type SkillSummary = {
  id: string
  tenant_id: string
  name: string
  domain: string
  status: string
  version: number
  visibility: string
  description: string
  source: string
  usage: SkillUsage
  workflow_id?: string | null
  updated_at: string | null
  created_at: string | null
}

export type SkillDetail = SkillSummary & {
  owner_user_id: string
  cot_template: string
  ir_skeleton: Record<string, unknown>
}

export type SkillEvolution = {
  total: number
  by_status: Record<string, number>
  mined_draft_queue: number
  total_uses: number
  cache_hit_rate_proxy: number
}

export async function listConsoleSkills(opts?: {
  q?: string
  status?: string
  domain?: string
}) {
  const p = new URLSearchParams()
  if (opts?.q) p.set('q', opts.q)
  if (opts?.status) p.set('status', opts.status)
  if (opts?.domain) p.set('domain', opts.domain)
  const qs = p.toString()
  return apiGet<{ items: SkillSummary[]; total: number }>(
    `/api/admin/console/skills${qs ? `?${qs}` : ''}`,
  )
}

export async function getSkillEvolution() {
  return apiGet<SkillEvolution>('/api/admin/console/skills/evolution')
}

export async function getConsoleSkill(assetId: string) {
  return apiGet<SkillDetail>(`/api/admin/console/skills/${encodeURIComponent(assetId)}`)
}

export async function publishConsoleSkill(assetId: string) {
  return apiPost<{ ok: boolean; item: SkillDetail }>(
    `/api/admin/console/skills/${encodeURIComponent(assetId)}/publish`,
    {},
  )
}

export async function deprecateConsoleSkill(assetId: string) {
  return apiPost<{ ok: boolean; item: SkillDetail }>(
    `/api/admin/console/skills/${encodeURIComponent(assetId)}/deprecate`,
    {},
  )
}

export async function rejectConsoleSkill(assetId: string) {
  return apiPost<{ ok: boolean; id: string }>(
    `/api/admin/console/skills/${encodeURIComponent(assetId)}/reject`,
    {},
  )
}

export type GuardrailRule = {
  id: string
  side: 'input' | 'output'
  rule_type: string
  name: string
  match: string
  action: 'block' | 'warn' | 'rewrite' | 'sanitize'
  priority: number
  enabled: boolean
  builtin: boolean
  description: string
  updated_at: string
}

export type GuardrailDryRunResult = {
  ok: boolean
  side: string
  final_action: string
  output_text: string
  hits: Array<{
    rule_id: string
    rule_name: string
    action: string
    reason: string
    builtin: boolean
  }>
  risk_policy: { risk_level: string; action: string } | null
}

export async function listGuardrailRules(opts?: { side?: string; enabled?: boolean }) {
  const p = new URLSearchParams()
  if (opts?.side) p.set('side', opts.side)
  if (opts?.enabled) p.set('enabled', 'true')
  const qs = p.toString()
  return apiGet<{ items: GuardrailRule[]; total: number }>(
    `/api/admin/console/guardrails/rules${qs ? `?${qs}` : ''}`,
  )
}

export async function createGuardrailRule(body: {
  side: 'input' | 'output'
  rule_type: string
  name: string
  match: string
  action: 'block' | 'warn' | 'rewrite' | 'sanitize'
  priority?: number
  enabled?: boolean
  description?: string
}) {
  return apiPost<{ ok: boolean; item: GuardrailRule }>(
    '/api/admin/console/guardrails/rules',
    body,
  )
}

export async function updateGuardrailRule(
  ruleId: string,
  body: Partial<{
    side: 'input' | 'output'
    rule_type: string
    name: string
    match: string
    action: 'block' | 'warn' | 'rewrite' | 'sanitize'
    priority: number
    enabled: boolean
    description: string
  }>,
) {
  return apiPut<{ ok: boolean; item: GuardrailRule }>(
    `/api/admin/console/guardrails/rules/${encodeURIComponent(ruleId)}`,
    body,
  )
}

export async function deleteGuardrailRule(ruleId: string) {
  return apiDelete<{ ok: boolean; id: string }>(
    `/api/admin/console/guardrails/rules/${encodeURIComponent(ruleId)}`,
  )
}

export async function getGuardrailRiskMatrix() {
  return apiGet<{
    levels: string[]
    matrix: Record<string, string>
    actions: string[]
  }>('/api/admin/console/guardrails/risk-matrix')
}

export async function putGuardrailRiskMatrix(matrix: Record<string, string>) {
  return apiPut<{ ok: boolean; matrix: Record<string, string> }>(
    '/api/admin/console/guardrails/risk-matrix',
    { matrix },
  )
}

export async function dryRunGuardrails(body: {
  side: 'input' | 'output'
  text: string
  risk_level?: string
}) {
  return apiPost<GuardrailDryRunResult>('/api/admin/console/guardrails/dry-run', body)
}
