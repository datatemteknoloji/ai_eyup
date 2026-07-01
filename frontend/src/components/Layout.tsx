import React, { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import {
  LayoutDashboard, Monitor, Cloud, Brain, ClipboardList, AlertTriangle, ScanSearch,
  MessageCircle, Bot, Zap, RefreshCw, Package, Database, Activity,
  ScrollText, Settings, LogOut, ChevronRight, ChevronLeft, Microscope, Sliders,
  HardDrive, BarChart3, Server, Shield, Layers,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'

interface LayoutProps {
  children: React.ReactNode
}

type ChildItem = { path: string; name: string; icon: React.ReactNode; badge?: () => React.ReactNode }
type MenuItem =
  | { type: 'link'; path: string; name: string; icon: React.ReactNode }
  | { type: 'group'; key: string; name: string; icon: React.ReactNode; children: ChildItem[] }
  | { type: 'section'; label: string }

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const location = useLocation()
  const { user, logout } = useAuth()
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  // All platform groups default open
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({
    linux: true, windows: true, virt: true, aiops: true, ai: false,
  })

  const { data: opsSummary } = useQuery<{ critical: number; warning: number; action_needed: boolean }>({
    queryKey: ['ops-summary-nav'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/ops/summary`)
      if (!r.ok) return { critical: 0, warning: 0, action_needed: false }
      return r.json()
    },
    refetchInterval: 30_000,
    staleTime: 20_000,
  })

  const isActive = (path: string) =>
    location.pathname === path || (path === '/dashboard' && location.pathname === '/')

  const isGroupActive = (paths: string[]) => paths.some(p => isActive(p))

  const toggleGroup = (key: string) =>
    setOpenGroups(prev => ({ ...prev, [key]: !prev[key] }))

  const menuItems: MenuItem[] = [
    // ── Overview ─────────────────────────────────────────────────────────
    { type: 'link', path: '/dashboard', name: 'Dashboard', icon: <LayoutDashboard size={18} /> },

    // ── Linux ─────────────────────────────────────────────────────────────
    {
      type: 'group', key: 'linux', name: 'Linux Yönetimi', icon: <Server size={18} />,
      children: [
        { path: '/servers',       name: 'Linux Sunucular',  icon: <Monitor size={15} /> },
        { path: '/metrics',       name: 'Canlı Metrikler',  icon: <Activity size={15} /> },
        { path: '/packages',      name: 'Paket & Yama',     icon: <Package size={15} /> },
        { path: '/system-update', name: 'Sistem Güncelle',  icon: <RefreshCw size={15} /> },
        { path: '/repositories',  name: 'Local Repo',       icon: <Database size={15} /> },
        { path: '/ansible',       name: 'Ansible/AWX',      icon: <Zap size={15} /> },
      ],
    },

    // ── Windows ───────────────────────────────────────────────────────────
    {
      type: 'group', key: 'windows', name: 'Windows Yönetimi', icon: <Shield size={18} />,
      children: [
        { path: '/windows',         name: 'Windows Sunucular', icon: <Monitor size={15} /> },
        { path: '/windows/events',  name: 'Event Log',         icon: <ClipboardList size={15} /> },
        { path: '/windows/updates', name: 'Windows Update',    icon: <RefreshCw size={15} /> },
      ],
    },

    // ── Virtualization ────────────────────────────────────────────────────
    {
      type: 'group', key: 'virt', name: 'Sanallaştırma', icon: <Cloud size={18} />,
      children: [
        { path: '/hypervisors',     name: 'Hypervisor\'lar',    icon: <Layers size={15} /> },
        { path: '/infra-reports',   name: 'Altyapı Raporları',  icon: <BarChart3 size={15} /> },
        { path: '/hypervisor-chat', name: 'Hypervisor Asistan', icon: <HardDrive size={15} /> },
      ],
    },

    // ── AIOps ─────────────────────────────────────────────────────────────
    {
      type: 'group', key: 'aiops', name: 'AIOps', icon: <Brain size={18} />,
      children: [
        {
          path: '/ops', name: 'Komuta Merkezi', icon: <Zap size={15} />,
          badge: () => (opsSummary?.critical ?? 0) > 0 ? (
            <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center animate-pulse">
              {opsSummary!.critical > 99 ? '99+' : opsSummary!.critical}
            </span>
          ) : null,
        },
        {
          path: '/events', name: 'Events', icon: <ClipboardList size={15} />,
          badge: () => (opsSummary?.warning ?? 0) > 0 ? (
            <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-amber-500 text-white text-[10px] font-bold flex items-center justify-center">
              {opsSummary!.warning > 99 ? '99+' : opsSummary!.warning}
            </span>
          ) : null,
        },
        { path: '/incidents',  name: 'Incidents',          icon: <AlertTriangle size={15} /> },
        { path: '/anomalies',  name: 'Anomaly Detection',  icon: <ScanSearch size={15} /> },
        { path: '/rca',        name: 'Kök Neden Analizi',  icon: <Microscope size={15} /> },
        { path: '/baseline',   name: 'Baseline Yönetimi',  icon: <Sliders size={15} /> },
      ],
    },

    // ── AI & Automation ───────────────────────────────────────────────────
    {
      type: 'group', key: 'ai', name: 'AI & Otomasyon', icon: <Bot size={18} />,
      children: [
        { path: '/chat',  name: 'AI Chat',  icon: <MessageCircle size={15} /> },
        { path: '/agent', name: 'AI Agent', icon: <Bot size={15} /> },
      ],
    },

    // ── System ────────────────────────────────────────────────────────────
    { type: 'link', path: '/audit',    name: 'Audit Log', icon: <ScrollText size={18} /> },
    { type: 'link', path: '/settings', name: 'Ayarlar',   icon: <Settings size={18} /> },
  ]

  // Flat link list for page title
  const allLinks: { path: string; name: string }[] = menuItems.flatMap(item => {
    if (item.type === 'link') return [{ path: item.path, name: item.name }]
    if (item.type === 'group') return item.children.map(c => ({ path: c.path, name: `${item.name} — ${c.name}` }))
    return []
  })

  const pageTitle = allLinks.find(l => isActive(l.path))?.name || 'Dashboard'

  const renderGroupItem = (item: Extract<MenuItem, { type: 'group' }>) => {
    const isOpen = openGroups[item.key] !== false
    const groupPaths = item.children.map(c => c.path)
    const groupActive = isGroupActive(groupPaths)

    return (
      <li key={`group-${item.key}`}>
        <button
          onClick={() => sidebarOpen && toggleGroup(item.key)}
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
            {item.children.map(child => {
              const childActive = isActive(child.path)
              const badge = child.badge?.()
              return (
                <li key={child.path}>
                  <Link
                    to={child.path}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all duration-200 text-sm ${
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
            })}
          </ul>
        )}

        {/* Collapsed: show all child icons */}
        {!sidebarOpen && (
          <div className="mt-0.5 space-y-0.5">
            {item.children.map(child => {
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
        <div className="h-14 flex items-center justify-between px-3 border-b border-slate-700 flex-shrink-0">
          {sidebarOpen && (
            <div className="flex items-center space-x-2">
              <div className="w-7 h-7 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-xs">DT</span>
              </div>
              <span className="text-white font-semibold text-sm">datatem AI</span>
            </div>
          )}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1.5 rounded-lg hover:bg-slate-700 text-slate-400 hover:text-white transition-colors flex-shrink-0"
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

              return renderGroupItem(item)
            })}
          </ul>
        </nav>

        {/* Footer */}
        <div className="p-3 border-t border-slate-700 flex-shrink-0">
          {sidebarOpen && (
            <div className="text-xs text-slate-500">
              <p>datatem AI v2.0</p>
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
                    <Link
                      to="/settings"
                      onClick={() => setUserMenuOpen(false)}
                      className="flex items-center gap-2 px-4 py-2.5 text-sm text-slate-300 hover:bg-slate-700/60"
                    >
                      <Settings size={14} /> Ayarlar
                    </Link>
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
    </div>
  )
}

export default Layout
