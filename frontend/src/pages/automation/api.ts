import { API_BASE_URL } from '../../config/api'

export const AUTOMATION_API = `${API_BASE_URL}/automation`

export type StatusClass = 'ok' | 'failed' | 'cancelled' | 'other' | string

export type Execution = {
  client: number
  run_id: number
  parent_run_id: number | null
  top_run_id: number | null
  restart_ref_run_id: number | null
  object_name: string
  object_type: string | null
  folder: string | null
  status_code: number | null
  status_class: StatusClass
  activation_time: string | null
  start_time: string | null
  end_time: string | null
  duration_sec: number | null
  agent: string | null
  platform: string | null
  queue: string | null
  user: string | null
  return_code: number | null
  run_time_sec?: number | null
  ert_sec?: number | null
  error_signature?: string | null
}

export type SystemHealth = {
  system_id: number
  name: string
  enabled: boolean
  fake: boolean
  clients: number[]
  source_label: string
  watermark: string | null
  last_run_at: string | null
  last_success_at: string | null
  next_run_at: string | null
  last_error: string | null
  last_rows: number | null
  last_duration_sec: number | null
  source_lag_sec: number | null
  source_lag_method: string | null
  active_snapshot_at: string | null
  ingest_paused_reason: string | null
  backfill_done: boolean
  circuit_open_sec: number
  interval_min: number
  failed_rule: string
  capability_at: string | null
  features: Record<string, boolean | string>
  database_role?: string | null
  database_role_display?: string
  role_drift?: boolean
  role_drift_message?: string | null
  source_info?: Record<string, any> | null
  live_read_mode?: string
  live_read_metrics?: {
    live_reads_ok_60m?: number
    live_reads_denied_60m?: number
    [k: string]: unknown
  }
  runs_24h?: { runs: number; errors: number; rows: number; avg_duration_sec: number | null }
}

export type AutomicSystem = {
  id: number
  name: string
  is_default: boolean
  enabled: boolean
  source_type: string
  connection: Record<string, any>
  has_secret: boolean
  clients: number[]
  settings: Record<string, any>
  capability_at: string | null
  capability_summary?: {
    engine?: string
    db_version?: string
    driver_mode?: string
    schema?: string
    database_role?: string
    database_role_display?: string
    timestamps?: string
    features?: Record<string, boolean | string>
    read_only_ok?: boolean
    warnings?: string[]
    clients_seen?: { client: number; count_24h: number; failed_24h: number }[]
  } | null
  capability?: Record<string, any> | null
  source_info?: Record<string, any> | null
  created_at: string | null
  updated_at: string | null
}

export type AutomationStatus = {
  db_available: boolean
  fake: boolean
  systems: SystemHealth[]
  quota?: {
    used_bytes: number
    quota_gb: number
    usage_pct: number
    level: string
    thresholds: { warn_pct: number; prune_pct: number; critical_pct: number }
  }
}

export type Overview = {
  system: string
  system_id: number
  clients: number[]
  from: string
  to: string
  bucket: 'hour' | 'day'
  generated_at: string
  kpi: {
    total: number; ok: number; failed: number; cancelled: number; other: number
    success_rate_pct: number | null; running: number
    previous: { total: number; ok: number; failed: number; cancelled: number; success_rate_pct: number | null }
  }
  status_distribution: {
    by_class: Record<string, number>
    by_code: { status_code: number; status_class: string; count: number }[]
  }
  volume: { bucket: string; ok: number; failed: number; cancelled: number; other: number }[]
  failure_trend: { day: string; failed: number; total: number }[]
  top_failed: { object_name: string; object_type: string | null; failed: number; runs: number }[]
  recent_failures: Execution[]
  health: SystemHealth & { series?: { t: string; rows: number; duration_sec: number; ok: boolean }[] }
  duration_outliers?: { object_name: string; run_id: number; client: number; duration_sec: number; p95_sec: number; ratio: number; end_time: string; status_class: string }[]
  duration_trend?: { object_name?: string | null; rows?: { bucket: string; avg_sec: number; p95_sec: number; max_sec: number; runs: number }[]; ok?: boolean }
  hourly_heatmap?: { dow: number; hour: number; total: number; failed: number }[]
  month_end_compare?: Record<string, any>[]
  agent_activity?: { agent: string; runs: number; failed: number; last_end: string | null; objects: number; active_now: number }[]
  active_workflows?: {
    total_active: number
    blocked: any[]
    workflows: any[]
    by_state: { running: number; waiting: number; blocked: number; other: number }
  }
  storage?: {
    used_bytes: number; quota_gb: number; usage_pct: number; level: string
    layers?: Record<string, number>
    thresholds?: { warn_pct: number; prune_pct: number; critical_pct: number }
  }
  expected_tonight?: {
    ok: boolean
    window_from?: string
    window_to?: string
    night_hours?: string
    note?: string
    items?: { object_name: string; object_type?: string; expected_at?: string; historical_runs?: number; typical_hour?: number; confidence?: string; avg_duration_sec?: number | null }[]
  }
}

export type DashboardInsight = {
  ok: boolean
  markdown: string
  cached?: boolean
  /** llm | deterministic */
  source?: string
  /** Arka planda LLM üretiliyor; UI kısa aralıklarla yenileyebilir */
  regenerating?: boolean
  generated_at?: string
  expires_in_sec?: number
  llm_error?: string | null
  findings?: { tone: string; text: string }[]
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function parse<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    const detail = typeof body?.detail === 'string' ? body.detail
      : Array.isArray(body?.detail) ? body.detail.map((d: any) => d?.msg).filter(Boolean).join('; ')
        : `HTTP ${r.status}`
    throw new ApiError(detail, r.status)
  }
  return r.json()
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export async function apiGet<T>(path: string): Promise<T> {
  return parse<T>(await fetch(`${AUTOMATION_API}${path}`))
}

export async function apiSend<T>(path: string, method: 'POST' | 'PUT' | 'DELETE', body?: unknown): Promise<T> {
  return parse<T>(await fetch(`${AUTOMATION_API}${path}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }))
}

export function executionPath(systemId: number, client: number, runId: number) {
  return `/automation/executions/${systemId}/${client}/${runId}`
}

export function objectPath(systemId: number, name: string) {
  return `/automation/objects/${systemId}/${encodeURIComponent(name)}`
}

export function agentPath(systemId: number, name: string) {
  return `/automation/agents/${systemId}/${encodeURIComponent(name)}`
}

export function engineServerPath(systemId: number, ip: string) {
  return `/automation/infrastructure/engines/${systemId}/${encodeURIComponent(ip)}`
}

// ── Altyapı (Infrastructure: agents / engine servers / AWI) ───────────────

export type InfraStatus = 'connected' | 'disconnected' | 'unknown' | 'missing'

export type InfraAgentListItem = {
  name: string
  ip: string | null
  hostname: string | null
  hostname_source: string | null
  hostname_source_label: string | null
  os: string | null
  platform: string | null
  version: string | null
  status: InfraStatus
  status_label: string
  status_rule: string | null
  last_life_sign: string | null
  missing_since: string | null
  synced_at: string | null
  groups: string[]
  teams?: string[]
  runs_24h: number
  failed_24h: number
  roles: string | null
}

export type InfraAgentsResponse = {
  ok: boolean
  system: string
  system_id: number
  agents: InfraAgentListItem[]
  synced_at: string | null
  source_now: string | null
  infra_warning?: string | null
  note?: string
  ae_version?: string | null
  ae_version_note?: string | null
}

export type InfraAgentIdentity = {
  name: string
  hostname: string | null
  hostname_source: string | null
  hostname_source_label: string | null
  hostname_automic: string | null
  hostname_manual: string | null
  hostname_mismatch: boolean
  ip: string | null
  os: string | null
  platform: string | null
  hardware: string | null
  version: string | null
  port: number | null
  roles: string | null
}

export type InfraAgentStatus = {
  value: InfraStatus
  label: string
  rule: string | null
  rule_label: string
  last_life_sign: string | null
  host_active: number | null
  missing_since: string | null
  synced_at: string | null
  source_now: string | null
  approx_uptime_pct: number | null
  uptime_note: string
  timeline_30d: { at: string; status: string }[]
}

export type InfraAgentDetail = {
  ok: boolean
  error?: string
  system?: string
  system_id?: number
  identity?: InfraAgentIdentity
  status?: InfraAgentStatus
  context?: { groups: string[]; teams: string[] }
  note?: string
}

export type EngineProcess = {
  name: string
  process_type: string
  ip: string | null
  port: number | null
  node: string | null
  hostname_source: string | null
  status: InfraStatus
  status_label: string
  last_life_sign: string | null
  connection_count: number | null
  pwp_connected: number | null
  rest_endpoint: string | null
  missing_since: string | null
  is_pwp: boolean
}

export type EngineServer = {
  ip: string
  node: string | null
  processes: EngineProcess[]
  has_active_pwp: boolean
}

export type InfraEnginesResponse = {
  ok: boolean
  system: string
  system_id: number
  servers: EngineServer[]
  synced_at: string | null
  source_now: string | null
  ae_version?: string | null
  ae_version_note?: string | null
  note?: string
}

export type InfraEngineServerDetail = {
  ok: boolean
  error?: string
  system?: string
  system_id?: number
  server?: EngineServer
  pwp_history: { at: string; name: string; status: string; ip?: string | null }[]
  synced_at?: string | null
  ae_version?: string | null
  ae_version_note?: string | null
  note?: string
}

export type AwiServer = {
  id: number
  name: string
  url: string
  enabled?: boolean
  last_status: string | null
  last_check_at: string | null
  last_http_code: number | null
  last_error: string | null
}

export type InfraAwiResponse = {
  ok: boolean
  system?: string
  system_id?: number
  awi_servers?: AwiServer[]
}
