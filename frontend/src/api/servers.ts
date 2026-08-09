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
  include_connection_config?: boolean
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
  if (params.include_connection_config) sp.set('include_connection_config', 'true')
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

export async function fetchServersSummary(platform?: string): Promise<ServerSummary> {
  const sp = platform ? `?platform=${encodeURIComponent(platform)}` : ''
  const r = await fetch(`${API_BASE_URL}/servers/summary${sp}`)
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
