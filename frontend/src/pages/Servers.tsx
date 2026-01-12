import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

const API_BASE_URL = 'http://192.168.1.166:8000/api/v1'

interface Server {
  id: number
  name: string
  hostname: string
  ip_address: string
  status: string
  os_type: string
  os_version: string
  server_type: string
  cpu_cores: number
  memory_gb: number
  ai_ready: boolean
  connection_config: any
  node_exporter?: {
    installed: boolean
    running: boolean
  }
}

const Servers: React.FC = () => {
  const [showAddModal, setShowAddModal] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('ONLINE') // Varsayılan olarak sadece online
  const [showOffline, setShowOffline] = useState(false) // Offline sunucuları göstermek için toggle
  const [aiReadyFilter, setAiReadyFilter] = useState<string>('all') // all, true, false
  const [installingNodeExporter, setInstallingNodeExporter] = useState<number | null>(null)
  const [formData, setFormData] = useState({
    name: '',
    hostname: '',
    ip_address: '',
    status: 'OFFLINE',
    server_type: 'VIRTUAL',
    os_type: 'linux'
  })

  const queryClient = useQueryClient()

  const { data: servers = [], isLoading } = useQuery<Server[]>({
    queryKey: ['servers'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/servers/?include_node_exporter_status=true`)
      if (!response.ok) throw new Error('Failed to fetch servers')
      return response.json()
    },
    refetchInterval: 30000 // 30 saniyede bir yenile
  })

  const createMutation = useMutation({
    mutationFn: async (data: typeof formData) => {
      const response = await fetch(`${API_BASE_URL}/servers/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to create server')
      }
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] })
      setShowAddModal(false)
      setFormData({ name: '', hostname: '', ip_address: '', status: 'OFFLINE', server_type: 'VIRTUAL', os_type: 'linux' })
    }
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await fetch(`${API_BASE_URL}/servers/${id}`, { method: 'DELETE' })
      if (!response.ok) throw new Error('Failed to delete server')
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] })
    }
  })

  const installNodeExporterMutation = useMutation({
    mutationFn: async (serverId: number) => {
      const response = await fetch(`${API_BASE_URL}/monitoring/node-exporter/install/${serverId}`, {
        method: 'POST'
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to install Node Exporter')
      }
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] })
      setInstallingNodeExporter(null)
    },
    onError: () => {
      setInstallingNodeExporter(null)
    }
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate(formData)
  }

  // Filtreleme
  const filteredServers = servers.filter(server => {
    const matchesSearch = server.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      server.ip_address?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      server.hostname?.toLowerCase().includes(searchTerm.toLowerCase())
    
    // Status filtresi: showOffline true ise tümü, false ise sadece ONLINE
    const matchesStatus = showOffline 
      ? (statusFilter === 'all' || server.status === statusFilter)
      : (server.status === 'ONLINE' || (statusFilter !== 'all' && server.status === statusFilter))
    
    const matchesAiReady = aiReadyFilter === 'all' || 
      (aiReadyFilter === 'true' && server.ai_ready) ||
      (aiReadyFilter === 'false' && !server.ai_ready)
    return matchesSearch && matchesStatus && matchesAiReady
  })

  const getStatusBadge = (status: string) => {
    const styles: Record<string, string> = {
      ONLINE: 'bg-green-500/20 text-green-400 border-green-500/30',
      OFFLINE: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
      WARNING: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
      CRITICAL: 'bg-red-500/20 text-red-400 border-red-500/30',
    }
    return styles[status] || styles.OFFLINE
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center space-x-4">
          {/* Search */}
          <div className="relative">
            <input
              type="text"
              placeholder="Sunucu ara..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-64 bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 pl-10 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <span className="absolute left-3 top-2.5 text-slate-500">🔍</span>
          </div>
          {/* Show Offline Toggle */}
          <label className="flex items-center space-x-2 cursor-pointer">
            <input
              type="checkbox"
              checked={showOffline}
              onChange={(e) => setShowOffline(e.target.checked)}
              className="w-4 h-4 text-blue-600 bg-slate-700 border-slate-600 rounded focus:ring-blue-500"
            />
            <span className="text-sm text-slate-300">Çevrimdışıları Göster</span>
          </label>
          {/* Status Filter */}
          {showOffline && (
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">Tüm Durumlar</option>
              <option value="ONLINE">Çevrimiçi</option>
              <option value="OFFLINE">Çevrimdışı</option>
              <option value="WARNING">Uyarı</option>
              <option value="CRITICAL">Kritik</option>
            </select>
          )}
          {/* AI Ready Filter */}
          <select
            value={aiReadyFilter}
            onChange={(e) => setAiReadyFilter(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">Tümü</option>
            <option value="true">🤖 AI Ready</option>
            <option value="false">AI Ready Değil</option>
          </select>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="inline-flex items-center px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all shadow-lg shadow-blue-500/25"
        >
          <span className="mr-2">➕</span>
          Yeni Sunucu
        </button>
      </div>

      {/* Table */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-900/50">
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Sunucu</th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">IP Adresi</th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Durum</th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Tip</th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Kaynaklar</th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">AI</th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Node Exporter</th>
                <th className="px-6 py-4 text-right text-xs font-medium text-slate-400 uppercase tracking-wider">İşlemler</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700">
              {filteredServers.map((server) => (
                <tr key={server.id} className="hover:bg-slate-700/30 transition-colors">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center">
                      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                        server.status === 'ONLINE' 
                          ? 'bg-gradient-to-br from-green-500 to-green-600' 
                          : 'bg-gradient-to-br from-slate-600 to-slate-700'
                      }`}>
                        <span className="text-white">🖥️</span>
                      </div>
                      <div className="ml-4">
                        <div className="text-sm font-medium text-white">{server.name}</div>
                        <div className="text-sm text-slate-400">{server.hostname}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm text-white font-mono">{server.ip_address || '-'}</div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${getStatusBadge(server.status)}`}>
                      ● {server.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm text-slate-300">{server.server_type}</div>
                    <div className="text-xs text-slate-500">{server.os_type || 'N/A'}</div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm text-slate-300">
                      {server.cpu_cores > 0 ? `${server.cpu_cores} CPU` : '-'}
                    </div>
                    <div className="text-xs text-slate-500">
                      {server.memory_gb > 0 ? `${server.memory_gb} GB RAM` : '-'}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {server.ai_ready ? (
                      <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-purple-500/20 text-purple-400 border border-purple-500/30">
                        🤖 Ready
                      </span>
                    ) : (
                      <span className="text-slate-500 text-sm">-</span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {server.connection_config?.username ? (
                      server.node_exporter?.installed ? (
                        server.node_exporter?.running ? (
                          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-green-500/20 text-green-400 border border-green-500/30">
                            ✅ Çalışıyor
                          </span>
                        ) : (
                          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-yellow-500/20 text-yellow-400 border border-yellow-500/30">
                            ⚠️ Kurulu (Durdurulmuş)
                          </span>
                        )
                      ) : (
                        <button
                          onClick={() => {
                            if (confirm(`${server.name} sunucusuna Node Exporter kurmak istediğinize emin misiniz?`)) {
                              setInstallingNodeExporter(server.id)
                              installNodeExporterMutation.mutate(server.id)
                            }
                          }}
                          disabled={installingNodeExporter === server.id}
                          className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-blue-500/20 text-blue-400 border border-blue-500/30 hover:bg-blue-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          title="Node Exporter Kur"
                        >
                          {installingNodeExporter === server.id ? '⏳ Kuruluyor...' : '📦 Kur'}
                        </button>
                      )
                    ) : (
                      <span className="text-slate-500 text-sm">-</span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right">
                    <div className="flex items-center justify-end space-x-2">
                      {installNodeExporterMutation.isError && installingNodeExporter === server.id && (
                        <span className="text-red-400 text-xs" title={installNodeExporterMutation.error?.message}>
                          ❌
                        </span>
                      )}
                      <button
                        onClick={() => {
                          if (confirm('Bu sunucuyu silmek istediğinize emin misiniz?')) {
                            deleteMutation.mutate(server.id)
                          }
                        }}
                        className="text-red-400 hover:text-red-300 transition-colors p-2"
                        title="Sil"
                      >
                        🗑️
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {filteredServers.length === 0 && (
          <div className="text-center py-12 text-slate-500">
            {searchTerm || statusFilter !== 'all' || aiReadyFilter !== 'all'
              ? 'Filtreye uygun sunucu bulunamadı' 
              : 'Henüz sunucu eklenmemiş'}
          </div>
        )}
      </div>

      {/* Add Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-6 w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-white">Yeni Sunucu Ekle</h2>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-slate-400 hover:text-white transition-colors"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Sunucu Adı *</label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="örn: web-server-01"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Hostname</label>
                <input
                  type="text"
                  value={formData.hostname}
                  onChange={(e) => setFormData({ ...formData, hostname: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="örn: web-server-01.local"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">IP Adresi</label>
                <input
                  type="text"
                  value={formData.ip_address}
                  onChange={(e) => setFormData({ ...formData, ip_address: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="örn: 192.168.1.100"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-2">Tip</label>
                  <select
                    value={formData.server_type}
                    onChange={(e) => setFormData({ ...formData, server_type: e.target.value })}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="VIRTUAL">Virtual</option>
                    <option value="PHYSICAL">Physical</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-2">İşletim Sistemi</label>
                  <select
                    value={formData.os_type}
                    onChange={(e) => setFormData({ ...formData, os_type: e.target.value })}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="linux">Linux</option>
                    <option value="windows">Windows</option>
                  </select>
                </div>
              </div>
              <div className="flex justify-end space-x-3 pt-4">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 bg-slate-700 text-white rounded-lg hover:bg-slate-600 transition-colors"
                >
                  İptal
                </button>
                <button
                  type="submit"
                  disabled={createMutation.isPending}
                  className="px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all disabled:opacity-50"
                >
                  {createMutation.isPending ? 'Ekleniyor...' : 'Ekle'}
                </button>
              </div>
              {createMutation.isError && (
                <p className="text-red-400 text-sm">
                  Hata: {createMutation.error instanceof Error ? createMutation.error.message : 'Bilinmeyen hata'}
                </p>
              )}
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

export default Servers
