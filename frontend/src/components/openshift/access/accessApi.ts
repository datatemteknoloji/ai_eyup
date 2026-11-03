import { API_BASE_URL } from '../../../config/api'

/** Cluster'a bağlı Access/RBAC çağrıları. Hata gövdesindeki `detail` (Türkçe) mesajı Error olarak fırlatılır. */
export async function accessRequest<T = any>(
  clusterId: number,
  path: string,
  opts: { params?: Record<string, string | undefined>; method?: 'GET' | 'POST'; body?: unknown } = {},
): Promise<T> {
  const p = new URLSearchParams()
  Object.entries(opts.params || {}).forEach(([k, v]) => { if (v !== undefined && v !== '') p.set(k, v) })
  const qs = p.toString()
  const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/access/${path}${qs ? `?${qs}` : ''}`, {
    method: opts.method || 'GET',
    headers: opts.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  })
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try {
      const j = await r.json()
      if (typeof j?.detail === 'string') msg = j.detail
      else if (Array.isArray(j?.detail)) msg = j.detail.map((d: any) => d.msg).join('; ')
    } catch { /* gövde JSON değil */ }
    throw new Error(msg)
  }
  return r.json()
}

export const MANAGED_BY_LABEL = 'app.kubernetes.io/managed-by'
export const isManagedByAinew = (labels?: Record<string, string>) => labels?.[MANAGED_BY_LABEL] === 'ainew'

export type AccessKind = 'RoleBinding' | 'ClusterRoleBinding' | 'Role' | 'ClusterRole'
export const ACCESS_KINDS: AccessKind[] = ['RoleBinding', 'ClusterRoleBinding', 'Role', 'ClusterRole']

export type Capabilities = {
  is_admin: boolean
  can_write: boolean
  reason: string
  kinds: Partial<Record<AccessKind, { allowed: boolean; reason: string }>>
}

export type Matrix = {
  columns: string[]
  rows: { api_group: string; resource: string; verbs: string[]; all_verbs: boolean; resource_names: string[]; restricted: boolean }[]
  non_resource: { urls: string[]; verbs: string[] }[]
  wildcard_verbs: boolean
  wildcard_resources: boolean
  full_access: boolean
}
