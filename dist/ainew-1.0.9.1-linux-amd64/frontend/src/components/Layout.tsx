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
  KeyRound, X, Check, AlertTriangle, Crown,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import {
  buildPlatformAiopsChildren,
  PLATFORM_AIOPS_LABEL,
} from '../config/platformAiops'

// ── Şifre Değiştir Modal ──────────────────────────────────────────────────────
function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [saving, setSaving] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (pw.length < 4) { setError('En az 4 karakter giriniz'); return }
    if (pw !== pw2) { setError('Şifreler eşleşmiyor'); return }
    setSaving(true); setError(null)
    try {
      const r = await fetch(`${API_BASE_URL}/auth/change-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: pw }),
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({}))
        throw new Error(err.detail ?? 'Hata oluştu')
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
            <KeyRound size={16} className="text-amber-400" /> Şifremi Değiştir
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
            <p className="text-white font-medium">Şifre güncellendi</p>
            <p className="text-slate-400 text-sm">Bir sonraki girişte yeni şifrenizi kullanın.</p>
            <button onClick={onClose}
              className="w-full py-2.5 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm transition-colors mt-2">
              Kapat
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className="p-6 space-y-4">
            <div>
              <label className="text-xs font-medium text-slate-400 mb-1.5 block">Yeni Şifre</label>
              <input value={pw} onChange={e => setPw(e.target.value)} type="password"
                placeholder="En az 4 karakter" required autoFocus
                className="w-full bg-slate-800 border border-slate-600 text-white text-sm rounded-xl px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-cyan-500/50" />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-400 mb-1.5 block">Yeni Şifre (Tekrar)</label>
              <input value={pw2} onChange={e => setPw2(e.target.value)} type="password"
                placeholder="Aynı şifreyi tekrar girin" required
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
                İptal
              </button>
              <button type="submit" disabled={saving}
                className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl bg-amber-600 hover:bg-amber-500 text-white font-medium text-sm disabled:opacity-60 transition-colors">
                {saving ? <RefreshCw size={13} className="animate-spin" /> : <KeyRound size={13} />}
                {saving ? '…' : 'Değiştir'}
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
}
type SubgroupChild = {
  type: 'subgroup'
  key: string
  name: string
  icon: React.ReactNode
  children: LinkChild[]
  moduleId?: string
  moduleIds?: string[]
}
type GroupChild = LinkChild | SubgroupChild
type MenuItem =
  | { type: 'link'; path: string; name: string; icon: React.ReactNode; moduleId?: string; moduleIds?: string[] }
  | { type: 'group'; key: string; name: string; icon: React.ReactNode; children: GroupChild[]; moduleId?: string; moduleIds?: string[] }
  | { type: 'section'; label: string }

function toLinkChildren(items: ReturnType<typeof buildPlatformAiopsChildren>): LinkChild[] {
  return items.map(c => ({ type: 'link', ...c }))
}

function collectGroupPaths(children: GroupChild[]): string[] {
  return children.flatMap(c => (c.type === 'link' ? [c.path] : collectGroupPaths(c.children)))
}

function childVisible(child: GroupChild, hasModule: (id: string) => boolean): boolean {
  const ids = child.moduleIds ?? (child.moduleId ? [child.moduleId] : undefined)
  if (ids && !ids.some(id => hasModule(id))) return false
  if (child.type === 'subgroup') {
    return child.children.some(c => childVisible(c, hasModule))
  }
  return true
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const location = useLocation()
  const { user, logout, hasModule } = useAuth()
  const { appName, logoUrl, version } = useBranding()
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [showChangePassword, setShowChangePassword] = useState(false)
  // All platform groups default closed
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({})

  const canLinuxAiops = hasModule('linux')

  const { data: opsSummary } = useQuery<{ critical: number; warning: number; action_needed: boolean }>({
    queryKey: ['ops-summary-nav'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/ops/summary?platform=linux`)
      if (!r.ok) return { critical: 0, warning: 0, action_needed: false }
      return r.json()
    },
    refetchInterval: 30_000,
    staleTime: 20_000,
    enabled: canLinuxAiops,
  })

  const { data: windowsOpsSummary } = useQuery<{ critical: number; warning: number; action_needed: boolean }>({
    queryKey: ['windows-ops-summary'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/ops/summary?platform=windows`)
      if (!r.ok) return { critical: 0, warning: 0, action_needed: false }
      return r.json()
    },
    refetchInterval: 30_000,
    staleTime: 20_000,
    enabled: hasModule('windows'),
  })

  const { data: virtOpsSummary } = useQuery<{ critical: number; warning: number; action_needed: boolean }>({
    queryKey: ['virt-ops-summary'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/ops/summary`)
      if (!r.ok) return { critical: 0, warning: 0, action_needed: false }
      return r.json()
    },
    refetchInterval: 30_000,
    staleTime: 20_000,
    enabled: hasModule('virtualization'),
  })

  const { data: exadataOpsSummary } = useQuery<{ critical: number; warning: number; action_needed: boolean }>({
    queryKey: ['exadata-ops-summary'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/exadata/ops/summary`)
      if (!r.ok) return { critical: 0, warning: 0, action_needed: false }
      return r.json()
    },
    refetchInterval: 30_000,
    staleTime: 20_000,
    enabled: hasModule('exadata'),
  })

  const isActive = (path: string) =>
    location.pathname === path ||
    (path === '/dashboard' && location.pathname === '/')

  const isGroupActive = (paths: string[]) => paths.some(p => isActive(p))

  const toggleGroup = (key: string, defaultOpen = false) =>
    setOpenGroups(prev => {
      const current = prev[key] ?? defaultOpen
      return { ...prev, [key]: !current }
    })

  const linuxAiopsLinks = toLinkChildren(buildPlatformAiopsChildren('linux', opsSummary))
  const virtAiopsLinks = toLinkChildren(buildPlatformAiopsChildren('virt', virtOpsSummary))
  const windowsAiopsLinks = toLinkChildren(buildPlatformAiopsChildren('windows', windowsOpsSummary))
  const exadataAiopsLinks = toLinkChildren(buildPlatformAiopsChildren('exadata', exadataOpsSummary))

  const menuItems: MenuItem[] = [
    // ── Genel dashboard (admin / çok modüllü özet) ────────────────────────
    { type: 'link', path: '/dashboard', name: 'Dashboard', icon: <LayoutDashboard size={18} /> },
    // ── Üst düzey yönetici özeti — tüm ortamlar tek ekranda ───────────────
    { type: 'link', path: '/executive', name: 'Yönetici Ekranı', icon: <Crown size={18} />, moduleId: 'executive' },

    // ── Linux ─────────────────────────────────────────────────────────────
    {
      type: 'group', key: 'linux', name: 'Linux Yönetimi', icon: <Server size={18} />, moduleId: 'linux',
      children: [
        { type: 'link', path: '/linux/dashboard', name: 'Dashboard',          icon: <LayoutDashboard size={15} />, moduleId: 'linux' },
        { type: 'link', path: '/servers',       name: 'Linux Sunucular',  icon: <Monitor size={15} />, moduleId: 'linux' },
        { type: 'link', path: '/metrics',       name: 'Canlı Metrikler',  icon: <Activity size={15} />, moduleId: 'linux' },
        { type: 'link', path: '/packages',      name: 'Paket & Yama',     icon: <Package size={15} />, moduleId: 'linux' },
        { type: 'link', path: '/system-update', name: 'Sistem Güncelle',  icon: <RefreshCw size={15} />, moduleId: 'linux' },
        { type: 'link', path: '/repositories',  name: 'Local Repo',       icon: <Database size={15} />, moduleId: 'linux' },
        { type: 'link', path: '/ansible',       name: 'Ansible/AWX',      icon: <Zap size={15} />, moduleId: 'linux' },
        { type: 'link', path: '/linux/reports', name: 'Altyapı Raporları', icon: <BarChart3 size={15} />, moduleId: 'linux' },
        {
          type: 'subgroup', key: 'linux-aiops', name: PLATFORM_AIOPS_LABEL.linux, icon: <Brain size={15} />,
          moduleId: 'linux',
          children: linuxAiopsLinks,
        },
      ],
    },

    // ── Windows ───────────────────────────────────────────────────────────
    {
      type: 'group', key: 'windows', name: 'Windows Yönetimi', icon: <Shield size={18} />, moduleId: 'windows',
      children: [
        { type: 'link', path: '/windows/dashboard', name: 'Dashboard',           icon: <LayoutDashboard size={15} /> },
        { type: 'link', path: '/windows',         name: 'Windows Sunucular', icon: <Monitor size={15} /> },
        { type: 'link', path: '/windows/live-metrics', name: 'Canlı Metrikler', icon: <Activity size={15} /> },
        { type: 'link', path: '/windows/events',  name: 'Event Log',         icon: <ClipboardList size={15} /> },
        { type: 'link', path: '/windows/updates', name: 'Windows Update',    icon: <RefreshCw size={15} /> },
        { type: 'link', path: '/windows/ansible', name: 'Ansible/AWX',       icon: <Zap size={15} /> },
        { type: 'link', path: '/windows/reports', name: 'Altyapı Raporları', icon: <BarChart3 size={15} /> },
        {
          type: 'subgroup', key: 'windows-aiops', name: PLATFORM_AIOPS_LABEL.windows, icon: <Brain size={15} />,
          moduleId: 'windows',
          children: windowsAiopsLinks,
        },
      ],
    },

    // ── Virtualization ────────────────────────────────────────────────────
    {
      type: 'group', key: 'virt', name: 'Sanallaştırma', icon: <Cloud size={18} />, moduleId: 'virtualization',
      children: [
        { type: 'link', path: '/hypervisors', name: 'Dashboard',          icon: <LayoutDashboard size={15} /> },
        { type: 'link', path: '/infra-reports', name: 'Altyapı Raporları',  icon: <BarChart3 size={15} /> },
        {
          type: 'subgroup', key: 'virt-aiops', name: PLATFORM_AIOPS_LABEL.virt, icon: <Brain size={15} />,
          moduleId: 'virtualization',
          children: virtAiopsLinks,
        },
      ],
    },

    // ── Exadata ───────────────────────────────────────────────────────────
    {
      type: 'group', key: 'exadata', name: 'Exadata', icon: <Layers size={18} />, moduleId: 'exadata',
      children: [
        { type: 'link', path: '/exadata', name: 'Envanter', icon: <LayoutDashboard size={15} /> },
        { type: 'link', path: '/exadata/reports', name: 'Altyapı Raporları', icon: <BarChart3 size={15} /> },
        {
          type: 'subgroup', key: 'exadata-aiops', name: PLATFORM_AIOPS_LABEL.exadata, icon: <Brain size={15} />,
          moduleId: 'exadata',
          children: exadataAiopsLinks,
        },
      ],
    },

    // ── AI & Automation ───────────────────────────────────────────────────
    { type: 'link', path: '/chat', name: 'Tüm Altyapı Analizi', icon: <Bot size={18} />, moduleIds: ['ai_automation', 'executive'] },

    // ── Integrations ──────────────────────────────────────────────────────
    {
      type: 'group', key: 'integrations', name: 'Entegrasyonlar', icon: <FileUp size={18} />, moduleId: 'integrations',
      children: [
        { type: 'link', path: '/integrations', name: 'Envanter Merkezi', icon: <Database size={15} /> },
        { type: 'link', path: '/integrations/ucmdb', name: 'UCMDB Import', icon: <FileUp size={15} /> },
        { type: 'link', path: '/integrations/hypervisors', name: 'vCenter / OLVM', icon: <Cloud size={15} /> },
        { type: 'link', path: '/integrations/physical-hosts', name: 'Fiziksel Hostlar', icon: <Server size={15} /> },
        { type: 'link', path: '/integrations/exadata', name: 'Exadata Envanter', icon: <Layers size={15} /> },
      ],
    },

    // ── Level 1 Operations ────────────────────────────────────────────────
    {
      type: 'group', key: 'level1', name: 'İşletim Level 1', icon: <Wrench size={18} />, moduleId: 'level1',
      children: [
        { type: 'link', path: '/level1',            name: 'Operasyon Merkezi', icon: <Wrench size={15} /> },
        { type: 'link', path: '/level1/disk',       name: 'Disk & Depolama',   icon: <HardDrive size={15} /> },
        { type: 'link', path: '/level1/asm',        name: 'Oracle ASM',        icon: <Database size={15} /> },
        { type: 'link', path: '/level1/lvm',        name: 'LVM Yönetimi',      icon: <Layers size={15} /> },
        { type: 'link', path: '/level1/service',    name: 'Servis Yönetimi',   icon: <Settings size={15} /> },
        { type: 'link', path: '/level1/user',       name: 'Kullanıcı & Erişim',icon: <Users size={15} /> },
      ],
    },

    // ── System ────────────────────────────────────────────────────────────
    { type: 'link', path: '/applications', name: 'Uygulamalar', icon: <Package size={18} /> },
    { type: 'link', path: '/knowledge-base', name: 'Bilgi Bankası', icon: <Brain size={18} /> },
    { type: 'link', path: '/audit',    name: 'Audit Log',          icon: <ScrollText size={18} /> },
    { type: 'link', path: '/users',    name: 'Kullanıcı Yönetimi', icon: <Users size={18} /> },
    { type: 'link', path: '/settings', name: 'Ayarlar',            icon: <Settings size={18} /> },
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

  const pageTitle = allLinks.find(l => isActive(l.path))?.name || 'Dashboard'

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
              : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
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
    if (!childVisible(child, hasModule)) return null

    if (child.type === 'link') {
      return renderLinkChild(child)
    }

    const subPaths = collectGroupPaths(child.children)
    const subActive = isGroupActive(subPaths)
    const isSubOpen = openGroups[child.key] ?? subActive

    return (
      <li key={child.key} className="pt-1">
        <button
          onClick={() => toggleGroup(child.key, subActive)}
          className={`w-full flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all duration-200 text-sm ${
            subActive ? 'text-white bg-slate-700/40' : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
          }`}
        >
          <span className="flex-shrink-0 text-current">{child.icon}</span>
          <span className="font-medium truncate flex-1 text-left">{child.name}</span>
          <ChevronRight size={12} className={`text-slate-500 transition-transform duration-200 flex-shrink-0 ${isSubOpen ? 'rotate-90' : ''}`} />
        </button>
        {isSubOpen && (
          <ul className="mt-0.5 ml-2 pl-2 border-l border-slate-700/40 space-y-0.5">
            {child.children.filter(c => childVisible(c, hasModule)).map(link => renderLinkChild(link, true))}
          </ul>
        )}
      </li>
    )
  }

  const renderGroupItem = (item: Extract<MenuItem, { type: 'group' }>) => {
    const visibleChildren = item.children.filter(c => childVisible(c, hasModule))
    const isOpen = openGroups[item.key] ?? isGroupActive(collectGroupPaths(visibleChildren))
    const groupPaths = collectGroupPaths(visibleChildren)
    const groupActive = isGroupActive(groupPaths)

    const flatLinks = visibleChildren.flatMap(c =>
      c.type === 'link' ? [c] : c.children.filter(l => childVisible(l, hasModule)),
    )

    return (
      <li key={`group-${item.key}`}>
        <button
          onClick={() => sidebarOpen && toggleGroup(item.key, groupActive)}
          className={`w-full flex items-center px-3 py-2 rounded-lg transition-all duration-200 ${
            groupActive
              ? 'text-white bg-slate-700/60'
              : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
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
                      : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
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
    <div className="min-h-screen bg-slate-900 flex">
      {/* Sidebar */}
      <aside className={`${sidebarOpen ? 'w-60' : 'w-16'} bg-slate-800 border-r border-slate-700 transition-all duration-300 flex flex-col flex-shrink-0`}>
        {/* Logo */}
        <div className={`${sidebarOpen ? 'min-h-[5.5rem] py-3' : 'h-14'} flex items-start justify-between px-3 border-b border-slate-700 flex-shrink-0 gap-1`}>
          {sidebarOpen && (
            <div className="flex flex-col items-start gap-2 min-w-0 flex-1 pt-0.5">
              {logoUrl ? (
                <img
                  src={logoUrl}
                  alt={appName}
                  className="h-12 w-auto max-w-full object-contain"
                />
              ) : (
                <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center">
                  <span className="text-white font-bold text-sm">DT</span>
                </div>
              )}
              <span className="text-white font-semibold text-sm leading-tight">{appName}</span>
            </div>
          )}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className={`p-1.5 rounded-lg hover:bg-slate-700 text-slate-400 hover:text-white transition-colors flex-shrink-0 ${!sidebarOpen ? 'mx-auto mt-2' : ''}`}
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
                    <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">
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
                          : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
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
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top Bar */}
        <header className="h-14 bg-slate-800 border-b border-slate-700 flex items-center justify-between px-5 flex-shrink-0">
          <div className="flex items-center gap-3">
            <h1 className="text-base font-semibold text-white">{pageTitle}</h1>
          </div>
          <div className="flex items-center space-x-4">
            <div className="flex items-center space-x-2 text-sm text-slate-400">
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
                    <div className="text-sm text-white font-medium">{user?.full_name || user?.username || 'Kullanıcı'}</div>
                    <div className="text-[10px] text-slate-400 uppercase">{user?.role || ''}</div>
                  </div>
                )}
                <div className="w-8 h-8 bg-gradient-to-br from-purple-500 to-pink-500 rounded-full flex items-center justify-center">
                  <span className="text-white text-sm font-medium">
                    {(user?.username || 'A').charAt(0).toUpperCase()}
                  </span>
                </div>
              </button>

              {userMenuOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setUserMenuOpen(false)} />
                  <div className="absolute right-0 mt-2 w-48 bg-slate-800 border border-slate-700 rounded-xl shadow-2xl z-20 overflow-hidden">
                    <div className="px-4 py-3 border-b border-slate-700">
                      <div className="text-sm text-white font-medium truncate">{user?.username}</div>
                      <div className="text-xs text-slate-400 truncate">{user?.email || '—'}</div>
                    </div>
                    <button
                      onClick={() => { setUserMenuOpen(false); setShowChangePassword(true) }}
                      className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-slate-300 hover:bg-slate-700/60"
                    >
                      <KeyRound size={14} /> Şifremi Değiştir
                    </button>
                    {user?.role === 'admin' && (
                      <Link
                        to="/settings"
                        onClick={() => setUserMenuOpen(false)}
                        className="flex items-center gap-2 px-4 py-2.5 text-sm text-slate-300 hover:bg-slate-700/60"
                      >
                        <Settings size={14} /> Ayarlar
                      </Link>
                    )}
                    <div className="border-t border-slate-700/60 my-1" />
                    <button
                      onClick={logout}
                      className="w-full flex items-center gap-2 text-left px-4 py-2.5 text-sm text-red-300 hover:bg-red-500/10"
                    >
                      <LogOut size={14} /> Çıkış Yap
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-auto p-5 bg-slate-900">
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
