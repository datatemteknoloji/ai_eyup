import React, { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'

interface LayoutProps {
  children: React.ReactNode
}

type MenuItem =
  | { type: 'link'; path: string; name: string; icon: string }
  | { type: 'group'; name: string; icon: string; children: { path: string; name: string; icon: string }[] }

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const location = useLocation()
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({ aiops: true })

  const isActive = (path: string) =>
    location.pathname === path || (path === '/dashboard' && location.pathname === '/')

  const isGroupActive = (paths: string[]) => paths.some(p => isActive(p))

  const toggleGroup = (key: string) =>
    setOpenGroups(prev => ({ ...prev, [key]: !prev[key] }))

  const menuItems: MenuItem[] = [
    { type: 'link', path: '/dashboard',    name: 'Dashboard',      icon: '📊' },
    { type: 'link', path: '/servers',      name: 'Sunucular',      icon: '🖥️' },
    { type: 'link', path: '/hypervisors',  name: 'Hypervisor\'lar', icon: '☁️' },
    {
      type: 'group', name: 'AIOps', icon: '🧠',
      children: [
        { path: '/events',    name: 'Events',            icon: '📋' },
        { path: '/incidents', name: 'Incidents',         icon: '🚨' },
        { path: '/anomalies', name: 'Anomaly Detection', icon: '🔍' },
      ],
    },
    { type: 'link', path: '/chat',         name: 'AI Chat',        icon: '🤖' },
    { type: 'link', path: '/ansible',      name: 'Ansible/AWX',    icon: '⚡' },
    { type: 'link', path: '/system-update', name: 'Sistem Güncelle', icon: '🔄' },
    { type: 'link', path: '/packages',     name: 'Paket & Yama',   icon: '📦' },
    { type: 'link', path: '/repositories', name: 'Local Repo',     icon: '🗄️' },
    { type: 'link', path: '/mcp',          name: 'Linux MCP',      icon: '🔧' },
    { type: 'link', path: '/metrics',      name: 'Canlı Metrikler', icon: '📈' },
    { type: 'link', path: '/settings',     name: 'Ayarlar',        icon: '⚙️' },
  ]

  // Flat list for top-bar title lookup
  const allLinks: { path: string; name: string }[] = menuItems.flatMap(item =>
    item.type === 'link'
      ? [{ path: item.path, name: item.name }]
      : item.children.map(c => ({ path: c.path, name: `AIOps — ${c.name}` }))
  )

  const pageTitle = allLinks.find(l => isActive(l.path))?.name || 'Dashboard'

  return (
    <div className="min-h-screen bg-slate-900 flex">
      {/* Sidebar */}
      <aside className={`${sidebarOpen ? 'w-64' : 'w-20'} bg-slate-800 border-r border-slate-700 transition-all duration-300 flex flex-col flex-shrink-0`}>
        {/* Logo */}
        <div className="h-16 flex items-center justify-between px-4 border-b border-slate-700">
          {sidebarOpen && (
            <div className="flex items-center space-x-2">
              <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-sm">DT</span>
              </div>
              <span className="text-white font-semibold">datatem AI</span>
            </div>
          )}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-2 rounded-lg hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
          >
            {sidebarOpen ? '◀' : '▶'}
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-4 overflow-y-auto">
          <ul className="space-y-0.5 px-3">
            {menuItems.map((item, idx) => {
              if (item.type === 'link') {
                const active = isActive(item.path)
                return (
                  <li key={item.path}>
                    <Link
                      to={item.path}
                      className={`flex items-center space-x-3 px-3 py-2.5 rounded-lg transition-all duration-200 ${
                        active
                          ? 'bg-gradient-to-r from-blue-600 to-blue-700 text-white shadow-lg shadow-blue-500/25'
                          : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
                      }`}
                    >
                      <span className="text-xl flex-shrink-0">{item.icon}</span>
                      {sidebarOpen && <span className="font-medium truncate">{item.name}</span>}
                    </Link>
                  </li>
                )
              }

              // Group
              const groupKey = item.name.toLowerCase().replace(/\s+/g, '')
              const isOpen = openGroups[groupKey] !== false
              const groupActive = isGroupActive(item.children.map(c => c.path))

              return (
                <li key={`group-${idx}`}>
                  {/* Group header */}
                  <button
                    onClick={() => sidebarOpen && toggleGroup(groupKey)}
                    className={`w-full flex items-center px-3 py-2.5 rounded-lg transition-all duration-200 ${
                      groupActive
                        ? 'text-white bg-slate-700/60'
                        : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
                    }`}
                  >
                    <span className="text-xl flex-shrink-0">{item.icon}</span>
                    {sidebarOpen && (
                      <>
                        <span className="font-medium ml-3 flex-1 text-left">{item.name}</span>
                        <span className={`text-xs text-slate-500 transition-transform duration-200 ${isOpen ? 'rotate-90' : ''}`}>
                          ▶
                        </span>
                      </>
                    )}
                  </button>

                  {/* Sub-items */}
                  {sidebarOpen && isOpen && (
                    <ul className="mt-0.5 ml-3 pl-3 border-l border-slate-700 space-y-0.5">
                      {item.children.map(child => {
                        const childActive = isActive(child.path)
                        return (
                          <li key={child.path}>
                            <Link
                              to={child.path}
                              className={`flex items-center space-x-2.5 px-3 py-2 rounded-lg transition-all duration-200 text-sm ${
                                childActive
                                  ? 'bg-gradient-to-r from-blue-600 to-blue-700 text-white shadow shadow-blue-500/20'
                                  : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
                              }`}
                            >
                              <span className="text-base flex-shrink-0">{child.icon}</span>
                              <span className="font-medium truncate">{child.name}</span>
                            </Link>
                          </li>
                        )
                      })}
                    </ul>
                  )}

                  {/* Collapsed: show group icon only, clicking goes to first child */}
                  {!sidebarOpen && (
                    <div className="mt-0.5 space-y-0.5">
                      {item.children.map(child => {
                        const childActive = isActive(child.path)
                        return (
                          <Link
                            key={child.path}
                            to={child.path}
                            title={`AIOps — ${child.name}`}
                            className={`flex items-center justify-center px-3 py-2 rounded-lg transition-all duration-200 ${
                              childActive
                                ? 'bg-gradient-to-r from-blue-600 to-blue-700 text-white'
                                : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
                            }`}
                          >
                            <span className="text-base">{child.icon}</span>
                          </Link>
                        )
                      })}
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-slate-700 flex-shrink-0">
          {sidebarOpen && (
            <div className="text-xs text-slate-500">
              <p>Server Management v1.0</p>
              <p className="mt-1">© 2026</p>
            </div>
          )}
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top Bar */}
        <header className="h-16 bg-slate-800 border-b border-slate-700 flex items-center justify-between px-6 flex-shrink-0">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold text-white">{pageTitle}</h1>
            <span className="px-2 py-0.5 rounded-full text-[10px] border border-cyan-500/50 text-cyan-200 bg-cyan-500/10">
              UI 2026
            </span>
          </div>
          <div className="flex items-center space-x-4">
            <div className="flex items-center space-x-2 text-sm text-slate-400">
              <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
              <span>Sistem Aktif</span>
            </div>
            <div className="w-8 h-8 bg-gradient-to-br from-purple-500 to-pink-500 rounded-full flex items-center justify-center">
              <span className="text-white text-sm font-medium">A</span>
            </div>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-auto p-6 bg-slate-900">
          {children}
        </main>
      </div>
    </div>
  )
}

export default Layout
