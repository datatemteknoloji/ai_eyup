import React, { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { useBranding } from '../branding/BrandingContext'
import {
  LayoutDashboard, Monitor, Cloud, Brain, ClipboardList,
  Bot, Zap, RefreshCw, Package, Database, Activity,
  ScrollText, Settings, LogOut, ChevronRight, ChevronLeft,
  BarChart3, Server, Shield, Layers, FileUp, Wrench, HardDrive, Users,
  KeyRound, X, Check, AlertTriangle, Crown, Boxes, Moon, Sun, Languages,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useTheme } from '../theme/ThemeProvider'
import { useLocale } from '../i18n/LocaleProvider'
import {
  buildPlatformAiopsChildren,
  PLATFORM_AIOPS_LABEL_KEY,
  aiopsTotalBadge,
} from '../config/platformAiops'

// ── Şifre Değiştir Modal ──────────────────────────────────────────────────────
function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const { t } = useLocale()
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [saving, setSaving] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (pw.length < 4) { setError(t('pw_min')); return }
    if (pw !== pw2) { setError(t('pw_mismatch')); return }
    setSaving(true); setError(null)
    try {
      const r = await fetch(`${API_BASE_URL}/auth/change-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: pw }),
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({}))
        throw new Error(err.detail ?? t('pw_error'))
      }
      setDone(true)
    } catch (e: any) { setError(e.message) }
    finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-sm shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/60">
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <KeyRound size={16} className="text-amber-400" /> {t('change_password')}
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-white transition-colors">
            <X size={18} />
          </button>
        </div>
        {done ? (
          <div className="p-6 text-center space-y-3">
            <div className="w-12 h-12 rounded-full bg-green-500/20 flex items-center justify-center mx-auto">
              <Check size={24} className="text-green-400" />
            </div>
            <p className="text-white font-medium">{t('pw_updated')}</p>
            <p className="text-slate-400 text-sm">{t('pw_updated_hint')}</p>
            <button onClick={onClose}
              className="w-full py-2.5 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm transition-colors mt-2">
              {t('close')}
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className="p-6 space-y-4">
            <div>
              <label className="text-xs font-medium text-slate-400 mb-1.5 block">{t('pw_new')}</label>
              <input value={pw} onChange={e => setPw(e.target.value)} type="password"
                placeholder={t('pw_placeholder')} required autoFocus
                className="w-full bg-slate-800 border border-slate-600 text-white text-sm rounded-xl px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-cyan-500/50" />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-400 mb-1.5 block">{t('pw_new_again')}</label>
              <input value={pw2} onChange={e => setPw2(e.target.value)} type="password"
                placeholder={t('pw_repeat_placeholder')} required
                className="w-full bg-slate-800 border border-slate-600 text-white text-sm rounded-xl px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-cyan-500/50" />
            </div>
            {error && (
              <p className="text-sm text-red-400 flex items-center gap-1.5">
                <AlertTriangle size={13} /> {error}
              </p>
            )}
            <div className="flex gap-3 pt-1">
              <button type="button" onClick={onClose}
                className="flex-1 py-2.5 rounded-xl border border-slate-600 text-slate-400 hover:bg-slate-800 text-sm transition-colors">
                {t('cancel')}
              </button>
              <button type="submit" disabled={saving}
                className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl bg-amber-600 hover:bg-amber-500 text-white font-medium text-sm disabled:opacity-60 transition-colors">
                {saving ? <RefreshCw size={13} className="animate-spin" /> : <KeyRound size={13} />}
                {saving ? '…' : t('pw_submit')}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

interface LayoutProps {
  children: React.ReactNode
}

type LinkChild = {
  type: 'link'
  path: string
  name: string
  icon: React.ReactNode
  badge?: () => React.ReactNode
  moduleId?: string
  moduleIds?: string[]
  adminOnly?: boolean
}
type SubgroupChild = {
  type: 'subgroup'
  key: string
  name: string
  icon: React.ReactNode
  children: LinkChild[]
  badge?: () => React.ReactNode
  moduleId?: string
  moduleIds?: string[]
  adminOnly?: boolean
}
type GroupChild = LinkChild | SubgroupChild
type MenuItem =
  | { type: 'link'; path: string; name: string; icon: React.ReactNode; moduleId?: string; moduleIds?: string[]; adminOnly?: boolean }
  | { type: 'group'; key: string; name: string; icon: React.ReactNode; children: GroupChild[]; moduleId?: string; moduleIds?: string[] }
  | { type: 'section'; label: string }

function toLinkChildren(items: ReturnType<typeof buildPlatformAiopsChildren>): LinkChild[] {
  return items.map(c => ({ type: 'link', ...c }))
}

function collectGroupPaths(children: GroupChild[]): string[] {
  return children.flatMap(c => (c.type === 'link' ? [c.path] : collectGroupPaths(c.children)))
}

function childVisible(
  child: GroupChild,
  hasModule: (id: string) => boolean,
  isAdmin: boolean,
): boolean {
  if (child.adminOnly && !isAdmin) return false
  const ids = child.moduleIds ?? (child.moduleId ? [child.moduleId] : undefined)
  if (ids && !ids.some(id => hasModule(id))) return false
  if (child.type === 'subgroup') {
    return child.children.some(c => childVisible(c, hasModule, isAdmin))
  }
  return true
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const location = useLocation()
  const { user, logout, hasModule } = useAuth()
  const isAdmin = user?.role === 'admin' || !!user?.is_admin
  const { theme, toggleTheme } = useTheme()
  const { t, locale, setLocale } = useLocale()
  const { appName, logoUrl, version } = useBranding()
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [showChangePassword, setShowChangePassword] = useState(false)
  // All platform groups default closed
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({})

  const canLinuxAiops = hasModule('linux')
  const canWindows = hasModule('windows')
  const canVirt = hasModule('virtualization')
  const canExadata = hasModule('exadata')
  const canOpenshift = hasModule('openshift')

  type NavOpsSummary = { critical: number; warning: number; total?: number; open_incidents?: number; action_needed: boolean }
  const emptyOps: NavOpsSummary = { critical: 0, warning: 0, total: 0, action_needed: false }

  // Tek query — 5 ayrı 60s poll yerine bir turda Promise.all (Wave 4)
  const { data: navOps } = useQuery<Record<string, NavOpsSummary>>({
    queryKey: ['nav-ops-summaries', canLinuxAiops, canWindows, canVirt, canExadata, canOpenshift],
    queryFn: async () => {
      const jobs: Array<Promise<[string, NavOpsSummary]>> = []
      const fetchOne = async (key: string, url: string): Promise<[string, NavOpsSummary]> => {
        try {
          const r = await fetch(url)
          if (!r.ok) return [key, emptyOps]
          return [key, await r.json()]
        } catch {
          return [key, emptyOps]
        }
      }
      if (canLinuxAiops) jobs.push(fetchOne('linux', `${API_BASE_URL}/ops/summary?platform=linux`))
      if (canWindows) jobs.push(fetchOne('windows', `${API_BASE_URL}/ops/summary?platform=windows`))
      if (canVirt) jobs.push(fetchOne('virt', `${API_BASE_URL}/hypervisors/ops/summary`))
      if (canExadata) jobs.push(fetchOne('exadata', `${API_BASE_URL}/exadata/ops/summary`))
      if (canOpenshift) jobs.push(fetchOne('openshift', `${API_BASE_URL}/openshift/ops/summary`))
      if (!jobs.length) return {}
      return Object.fromEntries(await Promise.all(jobs))
    },
    refetchInterval: 90_000,
    staleTime: 60_000,
    enabled: canLinuxAiops || canWindows || canVirt || canExadata || canOpenshift,
  })

  const opsSummary = navOps?.linux
  const windowsOpsSummary = navOps?.windows
  const virtOpsSummary = navOps?.virt
  const exadataOpsSummary = navOps?.exadata
  const openshiftOpsSummary = navOps?.openshift

  const isActive = (path: string) => {
    if (path === '/dashboard' && location.pathname === '/') return true
    if (path === '/openshift') {
      return location.pathname === '/openshift'
    }
    return location.pathname === path
  }

  const isGroupActive = (paths: string[]) => paths.some(p => isActive(p))

  const toggleGroup = (key: string, defaultOpen = false) =>
    setOpenGroups(prev => {
      const current = prev[key] ?? defaultOpen
      return { ...prev, [key]: !current }
    })

  const linuxAiopsLinks = toLinkChildren(buildPlatformAiopsChildren('linux', opsSummary, t))
  const virtAiopsLinks = toLinkChildren(buildPlatformAiopsChildren('virt', virtOpsSummary, t))
  const windowsAiopsLinks = toLinkChildren(buildPlatformAiopsChildren('windows', windowsOpsSummary, t))
  const exadataAiopsLinks = toLinkChildren(buildPlatformAiopsChildren('exadata', exadataOpsSummary, t))

  const menuItems: MenuItem[] = [
    { type: 'link', path: '/dashboard', name: t('nav_dashboard'), icon: <LayoutDashboard size={18} /> },
    {
      type: 'group', key: 'executive', name: t('nav_executive'), icon: <Crown size={18} />,
      moduleIds: ['executive', 'ai_automation'],
      children: [
        { type: 'link', path: '/executive', name: t('nav_executive_summary'), icon: <LayoutDashboard size={15} />, moduleId: 'executive' },
        { type: 'link', path: '/chat', name: t('nav_unified_chat'), icon: <Bot size={15} />, moduleIds: ['ai_automation', 'executive'] },
      ],
    },
    {
      type: 'group', key: 'linux', name: t('nav_linux'), icon: <Server size={18} />, moduleId: 'linux',
      children: [
        { type: 'link', path: '/linux/dashboard', name: t('nav_dashboard'), icon: <LayoutDashboard size={15} />, moduleId: 'linux' },
        { type: 'link', path: '/servers', name: t('nav_linux_servers'), icon: <Monitor size={15} />, moduleId: 'linux' },
        { type: 'link', path: '/metrics', name: t('nav_live_metrics'), icon: <Activity size={15} />, moduleId: 'linux' },
        { type: 'link', path: '/packages', name: t('nav_packages'), icon: <Package size={15} />, moduleId: 'linux' },
        { type: 'link', path: '/system-update', name: t('nav_system_update'), icon: <RefreshCw size={15} />, moduleId: 'linux' },
        { type: 'link', path: '/repositories', name: t('nav_local_repo'), icon: <Database size={15} />, moduleId: 'linux' },
        { type: 'link', path: '/ansible', name: t('nav_ansible_awx'), icon: <Zap size={15} />, moduleId: 'linux' },
        { type: 'link', path: '/linux/reports', name: t('nav_infra_reports'), icon: <BarChart3 size={15} />, moduleId: 'linux' },
        {
          type: 'subgroup', key: 'linux-aiops', name: t(PLATFORM_AIOPS_LABEL_KEY.linux), icon: <Brain size={15} />,
          moduleId: 'linux',
          badge: aiopsTotalBadge(opsSummary),
          children: linuxAiopsLinks,
        },
      ],
    },
    {
      type: 'group', key: 'windows', name: t('nav_windows'), icon: <Shield size={18} />, moduleId: 'windows',
      children: [
        { type: 'link', path: '/windows/dashboard', name: t('nav_dashboard'), icon: <LayoutDashboard size={15} /> },
        { type: 'link', path: '/windows', name: t('nav_windows_servers'), icon: <Monitor size={15} /> },
        { type: 'link', path: '/windows/live-metrics', name: t('nav_live_metrics'), icon: <Activity size={15} /> },
        { type: 'link', path: '/windows/events', name: t('nav_event_log'), icon: <ClipboardList size={15} /> },
        { type: 'link', path: '/windows/updates', name: t('nav_windows_update'), icon: <RefreshCw size={15} /> },
        { type: 'link', path: '/windows/ansible', name: t('nav_ansible_awx'), icon: <Zap size={15} /> },
        { type: 'link', path: '/windows/reports', name: t('nav_infra_reports'), icon: <BarChart3 size={15} /> },
        {
          type: 'subgroup', key: 'windows-aiops', name: t(PLATFORM_AIOPS_LABEL_KEY.windows), icon: <Brain size={15} />,
          moduleId: 'windows',
          badge: aiopsTotalBadge(windowsOpsSummary),
          children: windowsAiopsLinks,
        },
      ],
    },
    {
      type: 'group', key: 'virt', name: t('nav_virt'), icon: <Cloud size={18} />, moduleId: 'virtualization',
      children: [
        { type: 'link', path: '/hypervisors', name: t('nav_dashboard'), icon: <LayoutDashboard size={15} /> },
        { type: 'link', path: '/infra-reports', name: t('nav_infra_reports'), icon: <BarChart3 size={15} /> },
        {
          type: 'subgroup', key: 'virt-aiops', name: t(PLATFORM_AIOPS_LABEL_KEY.virt), icon: <Brain size={15} />,
          moduleId: 'virtualization',
          badge: aiopsTotalBadge(virtOpsSummary),
          children: virtAiopsLinks,
        },
      ],
    },
    {
      type: 'group', key: 'exadata', name: t('nav_exadata'), icon: <Layers size={18} />, moduleId: 'exadata',
      children: [
        { type: 'link', path: '/exadata', name: t('nav_inventory'), icon: <LayoutDashboard size={15} /> },
        { type: 'link', path: '/exadata/reports', name: t('nav_infra_reports'), icon: <BarChart3 size={15} /> },
        {
          type: 'subgroup', key: 'exadata-aiops', name: t(PLATFORM_AIOPS_LABEL_KEY.exadata), icon: <Brain size={15} />,
          moduleId: 'exadata',
          badge: aiopsTotalBadge(exadataOpsSummary),
          children: exadataAiopsLinks,
        },
      ],
    },
    {
      type: 'group', key: 'openshift', name: t('nav_openshift'), icon: <Boxes size={18} />, moduleId: 'openshift',
      children: [
        {
          type: 'link', path: '/openshift/ops', name: t('nav_command_center'), icon: <Zap size={15} />,
          badge: () => {
            const n = openshiftOpsSummary?.critical ?? 0
            if (n <= 0) return null
            return (
              <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center animate-pulse">
                {n > 99 ? '99+' : n}
              </span>
            )
          },
        },
        { type: 'link', path: '/openshift', name: t('nav_inventory'), icon: <LayoutDashboard size={15} /> },
        { type: 'link', path: '/openshift/vms', name: t('nav_virtual_machines'), icon: <Monitor size={15} /> },
        {
          type: 'link', path: '/openshift/events', name: t('nav_events'), icon: <ClipboardList size={15} />,
          badge: () => {
            const n = openshiftOpsSummary?.warning ?? 0
            if (n <= 0) return null
            return (
              <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-amber-500 text-white text-[10px] font-bold flex items-center justify-center">
                {n > 99 ? '99+' : n}
              </span>
            )
          },
        },
        {
          type: 'link', path: '/openshift/incidents', name: t('nav_incidents'), icon: <AlertTriangle size={15} />,
          badge: () => {
            const n = openshiftOpsSummary?.open_incidents ?? 0
            if (n <= 0) return null
            return (
              <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-amber-500 text-white text-[10px] font-bold flex items-center justify-center">
                {n > 99 ? '99+' : n}
              </span>
            )
          },
        },
        { type: 'link', path: '/openshift/chat', name: t('nav_assistant'), icon: <Brain size={15} /> },
      ],
    },
    {
      type: 'group', key: 'level1', name: t('nav_level1'), icon: <Wrench size={18} />, moduleId: 'level1',
      children: [
        { type: 'link', path: '/level1', name: t('nav_ops_center'), icon: <Wrench size={15} /> },
        { type: 'link', path: '/level1/jobs', name: t('nav_jobs'), icon: <ClipboardList size={15} /> },
        { type: 'link', path: '/level1/audit', name: t('nav_audit'), icon: <ScrollText size={15} />, adminOnly: true },
        { type: 'link', path: '/level1/settings', name: t('nav_settings'), icon: <Settings size={15} />, adminOnly: true },
      ],
    },
    {
      type: 'group', key: 'integrations', name: t('nav_integrations'), icon: <FileUp size={18} />, moduleId: 'integrations',
      children: [
        { type: 'link', path: '/integrations', name: t('nav_inventory_hub'), icon: <Database size={15} /> },
        { type: 'link', path: '/integrations/ucmdb', name: t('nav_ucmdb'), icon: <FileUp size={15} /> },
        { type: 'link', path: '/integrations/hypervisors', name: t('nav_vcenter_olvm'), icon: <Cloud size={15} /> },
        { type: 'link', path: '/integrations/physical-hosts', name: t('nav_physical_hosts'), icon: <Server size={15} /> },
        { type: 'link', path: '/integrations/exadata', name: t('nav_exadata_inventory'), icon: <Layers size={15} /> },
        { type: 'link', path: '/integrations/openshift', name: t('nav_openshift_inventory'), icon: <Boxes size={15} /> },
      ],
    },
    { type: 'link', path: '/applications', name: t('nav_applications'), icon: <Package size={18} />, moduleId: 'applications' },
    { type: 'link', path: '/knowledge-base', name: t('nav_knowledge'), icon: <Brain size={18} />, moduleId: 'knowledge' },
    { type: 'link', path: '/custom-reports', name: t('nav_custom_reports'), icon: <BarChart3 size={18} />, moduleId: 'custom_reports' },
    { type: 'link', path: '/audit', name: t('nav_audit_log'), icon: <ScrollText size={18} /> },
    { type: 'link', path: '/users', name: t('nav_users'), icon: <Users size={18} /> },
    { type: 'link', path: '/settings', name: t('nav_settings'), icon: <Settings size={18} /> },
  ]

  // Flat link list for page title
  const allLinks: { path: string; name: string }[] = menuItems.flatMap(item => {
    if (item.type === 'link') return [{ path: item.path, name: item.name }]
    if (item.type === 'group') {
      return item.children.flatMap(c => {
        if (c.type === 'link') return [{ path: c.path, name: `${item.name} — ${c.name}` }]
        return c.children.map(link => ({ path: link.path, name: `${item.name} — ${c.name} — ${link.name}` }))
      })
    }
    return []
  })

  const pageTitle = allLinks.find(l => isActive(l.path))?.name || t('nav_dashboard')

  const renderLinkChild = (child: LinkChild, indent = false) => {
    const childActive = isActive(child.path)
    const badge = child.badge?.()
    return (
      <li key={child.path}>
        <Link
          to={child.path}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all duration-200 text-sm ${
            indent ? 'pl-2' : ''
          } ${
            childActive
              ? 'bg-gradient-to-r from-blue-600 to-blue-700 text-white shadow shadow-blue-500/20'
              : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
          }`}
        >
          <span className="flex-shrink-0 text-current">{child.icon}</span>
          <span className="font-medium truncate flex-1">{child.name}</span>
          {badge}
        </Link>
      </li>
    )
  }

  const renderGroupChild = (child: GroupChild) => {
    if (!childVisible(child, hasModule, isAdmin)) return null

    if (child.type === 'link') {
      return renderLinkChild(child)
    }

    const subPaths = collectGroupPaths(child.children)
    const subActive = isGroupActive(subPaths)
    const isSubOpen = openGroups[child.key] ?? subActive
    const subBadge = child.badge?.()

    return (
      <li key={child.key} className="pt-1">
        <button
          onClick={() => toggleGroup(child.key, subActive)}
          className={`w-full flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all duration-200 text-sm ${
            subActive ? 'text-[var(--text-primary)] bg-[var(--bg-hover)]' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
          }`}
        >
          <span className="flex-shrink-0 text-current">{child.icon}</span>
          <span className="font-medium truncate flex-1 text-left">{child.name}</span>
          {subBadge}
          <ChevronRight size={12} className={`text-slate-500 transition-transform duration-200 flex-shrink-0 ${isSubOpen ? 'rotate-90' : ''}`} />
        </button>
        {isSubOpen && (
          <ul className="mt-0.5 ml-2 pl-2 border-l border-slate-700/40 space-y-0.5">
            {child.children.filter(c => childVisible(c, hasModule, isAdmin)).map(link => renderLinkChild(link, true))}
          </ul>
        )}
      </li>
    )
  }

  const renderGroupItem = (item: Extract<MenuItem, { type: 'group' }>) => {
    const visibleChildren = item.children.filter(c => childVisible(c, hasModule, isAdmin))
    const isOpen = openGroups[item.key] ?? isGroupActive(collectGroupPaths(visibleChildren))
    const groupPaths = collectGroupPaths(visibleChildren)
    const groupActive = isGroupActive(groupPaths)

    const flatLinks = visibleChildren.flatMap(c =>
      c.type === 'link' ? [c] : c.children.filter(l => childVisible(l, hasModule, isAdmin)),
    )

    return (
      <li key={`group-${item.key}`}>
        <button
          onClick={() => sidebarOpen && toggleGroup(item.key, groupActive)}
          className={`w-full flex items-center px-3 py-2 rounded-lg transition-all duration-200 ${
            groupActive
              ? 'text-[var(--text-primary)] bg-[var(--bg-hover)]'
              : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
          }`}
        >
          <span className="flex-shrink-0 text-current">{item.icon}</span>
          {sidebarOpen && (
            <>
              <span className="font-medium ml-3 flex-1 text-left text-sm">{item.name}</span>
              <ChevronRight size={13} className={`text-slate-500 transition-transform duration-200 ${isOpen ? 'rotate-90' : ''}`} />
            </>
          )}
        </button>

        {/* Expanded children */}
        {sidebarOpen && isOpen && (
          <ul className="mt-0.5 ml-3 pl-3 border-l border-slate-700/60 space-y-0.5">
            {visibleChildren.map(child => renderGroupChild(child))}
          </ul>
        )}

        {/* Collapsed: show all child icons */}
        {!sidebarOpen && (
          <div className="mt-0.5 space-y-0.5">
            {flatLinks.map(child => {
              const childActive = isActive(child.path)
              return (
                <Link
                  key={child.path}
                  to={child.path}
                  title={`${item.name} — ${child.name}`}
                  className={`flex items-center justify-center px-3 py-2 rounded-lg transition-all duration-200 ${
                    childActive
                      ? 'bg-gradient-to-r from-blue-600 to-blue-700 text-white'
                      : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
                  }`}
                >
                  <span className="flex-shrink-0 text-current">{child.icon}</span>
                </Link>
              )
            })}
          </div>
        )}
      </li>
    )
  }

  return (
    <div className="h-screen flex overflow-hidden" style={{ background: 'var(--bg-base)', color: 'var(--text-primary)' }}>
      {/* Sidebar — viewport'a sabit; yalnızca iç menü kayar */}
      <aside
        className={`app-sidebar ${sidebarOpen ? 'w-60' : 'w-16'} h-full border-r transition-all duration-300 flex flex-col flex-shrink-0`}
        style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-strong)' }}
      >
        {/* Logo */}
        <div
          className={`${sidebarOpen ? 'min-h-[5.5rem] py-3' : 'h-14'} flex items-start justify-between px-3 border-b flex-shrink-0 gap-1`}
          style={{ borderColor: 'var(--border-strong)' }}
        >
          {sidebarOpen && (
            <div className="flex flex-col items-start gap-2 min-w-0 flex-1 pt-0.5">
              {logoUrl ? (
                <img
                  src={logoUrl}
                  alt={appName}
                  className="h-12 w-auto max-w-full object-contain"
                />
              ) : (
                <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-sky-600 rounded-xl flex items-center justify-center">
                  <span className="text-white font-bold text-sm">DT</span>
                </div>
              )}
              <span className="font-semibold text-sm leading-tight" style={{ color: 'var(--text-primary)' }}>{appName}</span>
            </div>
          )}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className={`p-1.5 rounded-lg hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors flex-shrink-0 ${!sidebarOpen ? 'mx-auto mt-2' : ''}`}
          >
            {sidebarOpen ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-3 overflow-y-auto scrollbar-thin scrollbar-thumb-slate-700">
          <ul className="space-y-0.5 px-2">
            {menuItems.map((item, idx) => {
              if (item.type === 'section') {
                return sidebarOpen ? (
                  <li key={`sec-${idx}`} className="px-3 pt-3 pb-1">
                    <span className="app-sidebar-section text-[10px] font-semibold uppercase tracking-widest">
                      {item.label}
                    </span>
                  </li>
                ) : <li key={`sec-${idx}`} className="py-1"><div className="border-t border-slate-700/50 mx-2" /></li>
              }

              if (item.type === 'link') {
                // Kullanıcı Yönetimi ve Ayarlar sadece admin
                if ((item.path === '/modules' || item.path === '/users' || item.path === '/settings' || item.path === '/audit') && user?.role !== 'admin') return null
                {
                  const ids = item.moduleIds ?? (item.moduleId ? [item.moduleId] : undefined)
                  if (ids && !ids.some(id => hasModule(id))) return null
                }
                const active = isActive(item.path)
                return (
                  <li key={item.path}>
                    <Link
                      to={item.path}
                      title={!sidebarOpen ? item.name : undefined}
                      className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-200 ${
                        active
                          ? 'bg-gradient-to-r from-blue-600 to-blue-700 text-white shadow-lg shadow-blue-500/25'
                          : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
                      }`}
                    >
                      <span className="flex-shrink-0 text-current">{item.icon}</span>
                      {sidebarOpen && <span className="font-medium text-sm truncate">{item.name}</span>}
                    </Link>
                  </li>
                )
              }

              // Modül filtresi: moduleId veya moduleIds (OR) tanımlıysa erişim gerekli
              if (item.type === 'group') {
                const ids = item.moduleIds ?? (item.moduleId ? [item.moduleId] : undefined)
                if (ids && !ids.some(id => hasModule(id))) return null
              }

              return renderGroupItem(item)
            })}
          </ul>
        </nav>

        {/* Footer */}
        <div className="p-3 border-t border-slate-700 flex-shrink-0">
          {sidebarOpen && (
            <div className="text-xs text-slate-500">
              <p>{appName}{version ? ` v${version}` : ''}</p>
            </div>
          )}
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        {/* Top Bar */}
        <header
          className="h-14 border-b flex items-center justify-between px-5 flex-shrink-0"
          style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-strong)' }}
        >
          <div className="flex min-w-0 flex-1 items-center gap-3 pr-4">
            <h1 className="shrink-0 text-base font-semibold" style={{ color: 'var(--text-primary)' }}>{pageTitle}</h1>
            {/* Level 1 Operasyon Merkezi: Sunucular / envanter / yenile buraya portal ile gelir */}
            {(location.pathname === '/level1' || location.pathname === '/level1/') && (
              <div id="level1-ops-header-slot" className="flex min-w-0 flex-1 items-center gap-x-3 gap-y-1 overflow-hidden" />
            )}
          </div>
          <div className="flex items-center space-x-4">
            <div className="flex items-center space-x-2 text-sm" style={{ color: 'var(--text-secondary)' }}>
              <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
              <span className="hidden sm:inline">Sistem Aktif</span>
            </div>
            <div className="relative">
              <button
                onClick={() => setUserMenuOpen(o => !o)}
                className="flex items-center gap-2 group"
              >
                {sidebarOpen && (
                  <div className="text-right leading-tight hidden sm:block">
                    <div className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>{user?.full_name || user?.username || t('user_fallback')}</div>
                    <div className="text-[10px] uppercase" style={{ color: 'var(--text-muted)' }}>{user?.role || ''}</div>
                  </div>
                )}
                <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-sky-500 rounded-full flex items-center justify-center">
                  <span className="text-white text-sm font-medium">
                    {(user?.username || 'A').charAt(0).toUpperCase()}
                  </span>
                </div>
              </button>

              {userMenuOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setUserMenuOpen(false)} />
                  <div
                    className="absolute right-0 mt-2 w-52 border rounded-xl shadow-2xl z-20 overflow-hidden"
                    style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border-strong)' }}
                  >
                    <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--border-strong)' }}>
                      <div className="text-sm font-medium truncate" style={{ color: 'var(--text-primary)' }}>{user?.username}</div>
                      <div className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>{user?.email || '—'}</div>
                    </div>
                    <button
                      onClick={() => { toggleTheme(); }}
                      className="w-full flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-[var(--bg-hover)]"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
                      {theme === 'dark' ? t('theme_light') : t('theme_dark')}
                    </button>
                    <button
                      onClick={() => { setLocale(locale === 'tr' ? 'en' : 'tr') }}
                      className="w-full flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-[var(--bg-hover)]"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      <Languages size={14} />
                      {locale === 'tr' ? t('language_en') : t('language_tr')}
                    </button>
                    <button
                      onClick={() => { setUserMenuOpen(false); setShowChangePassword(true) }}
                      className="w-full flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-[var(--bg-hover)]"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      <KeyRound size={14} /> {t('change_password')}
                    </button>
                    {user?.role === 'admin' && (
                      <Link
                        to="/settings"
                        onClick={() => setUserMenuOpen(false)}
                        className="flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-[var(--bg-hover)]"
                        style={{ color: 'var(--text-secondary)' }}
                      >
                        <Settings size={14} /> {t('nav_settings')}
                      </Link>
                    )}
                    <div className="border-t my-1" style={{ borderColor: 'var(--border)' }} />
                    <button
                      onClick={logout}
                      className="w-full flex items-center gap-2 text-left px-4 py-2.5 text-sm text-red-400 hover:bg-red-500/10"
                    >
                      <LogOut size={14} /> {t('logout')}
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </header>

        {/* Page Content — chat/konsol tam ekran; diğer sayfalar main scroll */}
        <main
          className={`flex-1 min-h-0 p-5 ${
          (() => {
            const p = location.pathname
            const isChat = p.endsWith('/chat')
              || p.includes('/chat/')
              || p.includes('unified-chat')
              || /\/(linux|windows|virt|exadata|openshift)\/.*chat/.test(p)
            const isLevel1Fill = p.startsWith('/level1/console') || p.startsWith('/level1/ops')
            return (isChat || isLevel1Fill) ? 'overflow-hidden flex flex-col' : 'overflow-y-auto'
          })()
        }`}
          style={{ background: 'var(--bg-base)' }}
        >
          {children}
        </main>
      </div>

      {/* Şifre değiştir modal */}
      {showChangePassword && (
        <ChangePasswordModal onClose={() => setShowChangePassword(false)} />
      )}
    </div>
  )
}

export default Layout
