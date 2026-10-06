/**
 * Sayfa bazlı erişim tablosu (App.tsx rota korumalarının aynası).
 *
 * İlke: bir sayfaya yetkisi olan kullanıcı o sayfadaki her şeyi yapabilir; ancak sayfa
 * içindeki bir link / buton, yetkisi olmayan bir modülün sayfasına götüremez.
 * `canAccessPath` bu kararı tek yerden verir (LinkGuard tıklamayı engeller; rota
 * korumaları ise doğrudan URL / programatik navigate için son savunmadır).
 *
 * Tabloda olmayan yol → izinli (yönlendirme / ortak sayfalar; rota koruması geçerli).
 */
export type RouteReq = {
  /** any-of: listedeki modüllerden en az biri */
  modules?: string[]
  /** yalnız admin */
  admin?: boolean
  /** hem modül hem admin (örn. Level1 denetim) */
  moduleAndAdmin?: boolean
}

const M = (...modules: string[]): RouteReq => ({ modules })
const ADMIN: RouteReq = { admin: true }
/** OpenShift › Planlama ve Denetim: yalnız admin (operatör/viewer göremez). */
const ADMIN_OCP: RouteReq = { modules: ['openshift'], moduleAndAdmin: true }

export const ROUTE_ACCESS: Array<[string, RouteReq]> = [
  // ── Admin ──
  ['/users', ADMIN], ['/audit', ADMIN], ['/settings', ADMIN], ['/mcp', ADMIN],
  // ── Yönetici / izleme / sohbet ──
  ['/executive', M('executive')], ['/executive/reports', M('executive')],
  ['/monitoring', M('monitoring')],
  ['/chat', M('ai_automation', 'executive')],
  ['/agent', M('ai_automation')],
  // ── Linux ──
  ['/linux/dashboard', M('linux')], ['/linux/reports', M('linux')],
  ['/linux/ops', M('linux')], ['/linux/chat', M('linux')], ['/linux/events', M('linux')],
  ['/linux/incidents', M('linux')], ['/linux/analysis', M('linux')],
  ['/servers', M('linux')], ['/metrics', M('linux')], ['/ansible', M('linux')],
  ['/packages', M('linux')], ['/repositories', M('linux')], ['/system-update', M('linux')],
  ['/terminal/:id', M('linux')],
  // ── Windows ──
  ['/windows', M('windows')], ['/windows/dashboard', M('windows')], ['/windows/reports', M('windows')],
  ['/windows/live-metrics', M('windows')], ['/windows/events', M('windows')],
  ['/windows/updates', M('windows')], ['/windows/ansible', M('windows')],
  ['/windows/aiops/ops', M('windows')], ['/windows/aiops/chat', M('windows')],
  ['/windows/aiops/events', M('windows')], ['/windows/aiops/incidents', M('windows')],
  ['/windows/aiops/analysis', M('windows')],
  // ── Sanallaştırma ──
  ['/hypervisors', M('virtualization')], ['/infra-reports', M('virtualization')],
  ['/virt/monitoring', M('virtualization')], ['/virt/capacity', M('virtualization')],
  ['/virt/reclaim', M('virtualization')], ['/virt/health', M('virtualization')],
  ['/virt/changes', M('virtualization')], ['/virt/ops', M('virtualization')],
  ['/virt/chat', M('virtualization')], ['/virt/events', M('virtualization')],
  ['/virt/incidents', M('virtualization')], ['/virt/analysis', M('virtualization')],
  // ── Exadata ──
  ['/exadata', M('exadata')], ['/exadata/reports', M('exadata')], ['/exadata/chat', M('exadata')],
  ['/exadata/ops', M('exadata')], ['/exadata/events', M('exadata')],
  ['/exadata/incidents', M('exadata')], ['/exadata/analysis', M('exadata')],
  // ── OpenShift ──
  ['/openshift', M('openshift')], ['/openshift/vms', M('openshift')],
  ['/openshift/vms/:c/:ns/:n/console', M('openshift')],
  ['/openshift/monitoring', M('openshift')], ['/openshift/access', M('openshift')],
  ['/openshift/capacity', ADMIN_OCP], ['/openshift/reclaim', ADMIN_OCP],
  ['/openshift/health', ADMIN_OCP], ['/openshift/changes', ADMIN_OCP],
  ['/openshift/chat', M('openshift')], ['/openshift/ops', M('openshift')],
  ['/openshift/events', M('openshift')], ['/openshift/incidents', M('openshift')],
  // ── Entegrasyonlar ──
  ['/integrations', M('integrations')], ['/integrations/ucmdb', M('integrations')],
  ['/integrations/physical-hosts', M('integrations')],
  ['/integrations/hypervisors', M('integrations', 'virtualization')],
  ['/integrations/exadata', M('integrations', 'exadata')],
  ['/integrations/openshift', M('integrations', 'openshift')],
  ['/integrations/centrify', M('integrations', 'level1')],
  // ── Level 1 ──
  ['/level1', M('level1')], ['/level1/ops/*', M('level1')], ['/level1/console/:id', M('level1')],
  ['/level1/jobs/*', M('level1')], ['/level1/centrify', M('level1')],
  ['/level1/audit', { modules: ['level1'], moduleAndAdmin: true }],
  ['/level1/settings', { modules: ['level1'], moduleAndAdmin: true }],
  // ── Ayrı atama gerektiren sayfalar ──
  ['/knowledge-base', M('knowledge')], ['/applications', M('applications')],
  ['/custom-reports', M('custom_reports')],
]

function toRegex(pattern: string): RegExp {
  const esc = pattern
    .replace(/[.+?^${}()|[\]\\]/g, '\\$&')
    .replace(/:[A-Za-z0-9_]+/g, '[^/]+')
    .replace(/\/\*$/, '(?:/.*)?')
  return new RegExp(`^${esc}$`)
}

const COMPILED = ROUTE_ACCESS.map(([p, req]) => ({ rx: toRegex(p), req }))

/** Yol (query/hash hariç) için gereksinim; tabloda yoksa null. */
export function routeRequirement(pathname: string): RouteReq | null {
  const p = (pathname.replace(/\/+$/, '') || '/')
  for (const { rx, req } of COMPILED) if (rx.test(p)) return req
  return null
}

export function canAccessPath(
  pathname: string,
  hasModule: (id: string) => boolean,
  isAdmin: boolean,
): boolean {
  const req = routeRequirement(pathname)
  if (!req) return true
  if (isAdmin) return true
  if (req.admin) return false
  if (req.moduleAndAdmin) return false // modül + admin gerektirir; admin yukarıda geçti
  if (req.modules && !req.modules.some((m) => hasModule(m))) return false
  return true
}
