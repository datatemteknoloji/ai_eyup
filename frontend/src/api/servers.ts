import { API_BASE_URL } from '../config/api'

export type Paginated<T> = {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type ServerSummary = {
  total: number
  online: number
  offline: number
  warning?: number
  critical?: number
  ai_ready: number
  node_exporter_installed: number
  node_exporter_running: number
  name_mismatch?: number
  cpu_cores?: number
  memory_gb?: number
  by_status: Record<string, number>
  by_os: Record<string, number>
}

export type ListServersParams = {
  platform?: string
  page?: number
  page_size?: number
  q?: string
  status?: string
  hide_offline?: boolean
  ai_ready?: boolean | null
  server_type?: string
  os?: string
  node_exporter?: string
  ip?: string
  name_mismatch?: boolean | null
  include_connection_config?: boolean
  hypervisor_id?: number
  hypervisor_type?: string
  hypervisor_types?: string
  /** Virgüllü ortam (hypervisor) id'leri; unassigned_hypervisor ile OR'lanır. */
  hypervisor_ids?: string
  unassigned_hypervisor?: boolean
  /** name | ip_address | status | os_type | cpu_cores | memory_gb | server_type | ai_ready */
  sort_by?: string
  sort_dir?: 'asc' | 'desc'
}

/** Parse list API — supports new `{items,...}` and legacy raw arrays. */
export function unwrapPaginated<T = unknown>(data: unknown): Paginated<T> {
  if (Array.isArray(data)) {
    return { items: data as T[], total: data.length, page: 1, page_size: data.length || 50 }
  }
  if (data && typeof data === 'object' && Array.isArray((data as Paginated<T>).items)) {
    const p = data as Paginated<T>
    return {
      items: p.items,
      total: Number(p.total) || p.items.length,
      page: Number(p.page) || 1,
      page_size: Number(p.page_size) || p.items.length || 50,
    }
  }
  return { items: [], total: 0, page: 1, page_size: 50 }
}

export async function fetchServersPage<T = Record<string, unknown>>(
  params: ListServersParams = {},
): Promise<Paginated<T>> {
  const sp = new URLSearchParams()
  if (params.platform) sp.set('platform', params.platform)
  sp.set('page', String(params.page ?? 1))
  sp.set('page_size', String(params.page_size ?? 50))
  if (params.q) sp.set('q', params.q)
  if (params.status && params.status !== 'all') sp.set('status', params.status)
  if (params.hide_offline) sp.set('hide_offline', 'true')
  if (params.ai_ready === true) sp.set('ai_ready', 'true')
  if (params.ai_ready === false) sp.set('ai_ready', 'false')
  if (params.server_type && params.server_type !== 'all') sp.set('server_type', params.server_type)
  if (params.os && params.os !== 'all') sp.set('os', params.os)
  if (params.node_exporter && params.node_exporter !== 'all') sp.set('node_exporter', params.node_exporter)
  if (params.ip) sp.set('ip', params.ip)
  if (params.name_mismatch === true) sp.set('name_mismatch', 'true')
  if (params.include_connection_config) sp.set('include_connection_config', 'true')
  if (params.hypervisor_id != null) sp.set('hypervisor_id', String(params.hypervisor_id))
  if (params.hypervisor_type) sp.set('hypervisor_type', params.hypervisor_type)
  if (params.hypervisor_types) sp.set('hypervisor_types', params.hypervisor_types)
  if (params.hypervisor_ids) sp.set('hypervisor_ids', params.hypervisor_ids)
  if (params.unassigned_hypervisor) sp.set('unassigned_hypervisor', 'true')
  if (params.sort_by) {
    sp.set('sort_by', params.sort_by)
    sp.set('sort_dir', params.sort_dir ?? 'asc')
  }
  const r = await fetch(`${API_BASE_URL}/servers/?${sp}`)
  if (!r.ok) {
    let detail = `HTTP ${r.status}`
    try {
      const err = await r.json()
      detail = typeof err?.detail === 'string' ? err.detail : JSON.stringify(err)
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  return unwrapPaginated<T>(await r.json())
}

/** Dropdown / picker: up to `maxPages * page_size` slim rows. */
export async function fetchServersForPicker<T = Record<string, unknown>>(opts: {
  platform?: string
  q?: string
  page_size?: number
  maxPages?: number
} = {}): Promise<T[]> {
  const page_size = opts.page_size ?? 200
  const maxPages = opts.maxPages ?? 1
  const items: T[] = []
  for (let page = 1; page <= maxPages; page += 1) {
    const p = await fetchServersPage<T>({
      platform: opts.platform,
      q: opts.q,
      page,
      page_size,
    })
    items.push(...p.items)
    if (items.length >= p.total || p.items.length === 0) break
  }
  return items
}

export async function fetchServersSummary(
  platform?: string,
  extra: { hypervisor_id?: number; hypervisor_type?: string; hypervisor_types?: string; hypervisor_ids?: string; unassigned_hypervisor?: boolean } = {},
): Promise<ServerSummary> {
  const sp = new URLSearchParams()
  if (platform) sp.set('platform', platform)
  if (extra.hypervisor_id != null) sp.set('hypervisor_id', String(extra.hypervisor_id))
  if (extra.hypervisor_type) sp.set('hypervisor_type', extra.hypervisor_type)
  if (extra.hypervisor_types) sp.set('hypervisor_types', extra.hypervisor_types)
  if (extra.hypervisor_ids) sp.set('hypervisor_ids', extra.hypervisor_ids)
  if (extra.unassigned_hypervisor) sp.set('unassigned_hypervisor', 'true')
  const q = sp.toString()
  const r = await fetch(`${API_BASE_URL}/servers/summary${q ? `?${q}` : ''}`)
  if (!r.ok) throw new Error(`summary HTTP ${r.status}`)
  return r.json()
}

export async function fetchAiReadyPage<T = Record<string, unknown>>(opts: {
  platform?: string
  page?: number
  page_size?: number
  q?: string
} = {}): Promise<Paginated<T>> {
  const sp = new URLSearchParams()
  if (opts.platform) sp.set('platform', opts.platform)
  sp.set('page', String(opts.page ?? 1))
  sp.set('page_size', String(opts.page_size ?? 200))
  if (opts.q) sp.set('q', opts.q)
  const r = await fetch(`${API_BASE_URL}/servers/ai-ready/list?${sp}`)
  if (!r.ok) throw new Error(`ai-ready HTTP ${r.status}`)
  return unwrapPaginated<T>(await r.json())
}

// ── Ortam (hypervisor) facet'leri ───────────────────────────────────────────────

export type HypervisorFacetEnv = { id: number; name: string; status: string; count: number }
export type HypervisorFacetGroup = { type: string; label: string; environments: HypervisorFacetEnv[] }
export type HypervisorFacets = { groups: HypervisorFacetGroup[]; unassigned_count: number }

/** Hypervisor filtreleri HARİÇ liste filtreleri (sayılar bunlarla hesaplanır). */
export type HypervisorFacetFilters = {
  q?: string
  status?: string
  hide_offline?: boolean
  ai_ready?: boolean | null
  server_type?: string
  node_exporter?: string
  name_mismatch?: boolean | null
  os?: string
  /** Yalnızca Windows: sınıflandırılmamış VM'ler dahil mi */
  include_unclassified?: boolean
}

export async function fetchHypervisorFacets(
  platform: 'linux' | 'windows',
  f: HypervisorFacetFilters = {},
): Promise<HypervisorFacets> {
  const sp = new URLSearchParams()
  if (f.q) sp.set('q', f.q)
  if (f.status && f.status !== 'all') sp.set('status', f.status)
  if (f.hide_offline) sp.set('hide_offline', 'true')
  if (f.ai_ready === true) sp.set('ai_ready', 'true')
  if (f.ai_ready === false) sp.set('ai_ready', 'false')
  if (f.server_type && f.server_type !== 'all') sp.set('server_type', f.server_type)
  if (f.node_exporter && f.node_exporter !== 'all') sp.set('node_exporter', f.node_exporter)
  if (f.name_mismatch === true) sp.set('name_mismatch', 'true')
  if (f.os && f.os !== 'all') sp.set('os', f.os)
  if (f.include_unclassified) sp.set('include_unclassified', 'true')
  // Windows sayfası kendi (windows modülü) ucunu kullanır; Linux /servers.
  const url = platform === 'windows'
    ? `${API_BASE_URL}/windows/servers/hypervisor-facets`
    : `${API_BASE_URL}/servers/hypervisor-facets`
  if (platform === 'linux') sp.set('platform', 'linux')
  const r = await fetch(`${url}?${sp}`)
  if (!r.ok) throw new Error(`hypervisor-facets HTTP ${r.status}`)
  const d = await r.json()
  return {
    groups: Array.isArray(d?.groups) ? d.groups : [],
    unassigned_count: Number(d?.unassigned_count) || 0,
  }
}
