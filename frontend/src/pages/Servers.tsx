import React, { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

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

const NODE_EXPORTER_STEP_LABELS = [
  { id: 'connection', label: 'SSH bağlantı testi' },
  { id: 'status_check', label: 'Node Exporter durum kontrolü' },
  { id: 'download', label: 'Binary indirme / dağıtım' },
  { id: 'install', label: 'Sunucuya kurulum' },
  { id: 'systemd_service', label: 'Systemd servisi oluşturma' },
  { id: 'start_service', label: 'Servisi başlatma' },
  { id: 'final_check', label: 'Son durum kontrolü' },
  { id: 'prometheus', label: 'Prometheus hedefi ekleme' }
]

const Servers: React.FC = () => {
  const [showAddModal, setShowAddModal] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [ipFilter, setIpFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all') // Varsayılan olarak tüm durumlar
  const [showOffline, setShowOffline] = useState(true) // Varsayılan: tüm sunucular (çevrimiçi + çevrimdışı) gösterilsin
  const [aiReadyFilter, setAiReadyFilter] = useState<string>('all') // all, true, false
  const [typeFilter, setTypeFilter] = useState<string>('all') // all, VIRTUAL, PHYSICAL
  const [nodeExporterFilter, setNodeExporterFilter] = useState<string>('all') // all, installed, running, not_installed

  const [sortKey, setSortKey] = useState<string>('name')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')
  const [installingNodeExporter, setInstallingNodeExporter] = useState<number | null>(null)
  const [startingNodeExporter, setStartingNodeExporter] = useState<number | null>(null)
  const [installResultByServerId, setInstallResultByServerId] = useState<Record<number, {
    success: boolean
    message?: string
    error?: string
    steps?: Array<{ id: string; label: string; status: string; message?: string }>
  }>>({})
  const [installSimulatedStep, setInstallSimulatedStep] = useState<Record<number, number>>({})
  const installAbortRef = React.useRef<AbortController | null>(null)
  const [formData, setFormData] = useState({
    name: '',
    hostname: '',
    ip_address: '',
    status: 'OFFLINE',
    server_type: 'VIRTUAL',
    os_type: 'linux',
    ssh_username: '',
    ssh_password: '',
    ssh_port: '22',
    sudo_password: '',
    private_key: ''
  })

  const queryClient = useQueryClient()

  // Kurulum sırasında adımların görsel olarak ilerlemesi (simüle)
  useEffect(() => {
    if (installingNodeExporter == null) return
    setInstallSimulatedStep(prev => ({ ...prev, [installingNodeExporter]: 0 }))
    const totalSteps = 8
    const t = setInterval(() => {
      setInstallSimulatedStep(prev => {
        const current = prev[installingNodeExporter] ?? 0
        if (current >= totalSteps - 1) return prev
        return { ...prev, [installingNodeExporter]: current + 1 }
      })
    }, 2200)
    return () => clearInterval(t)
  }, [installingNodeExporter])

  // Önce sunucu listesini al (Node Exporter durumu olmadan)
  const { data: servers = [], isLoading, isFetching, isError, error, refetch } = useQuery<Server[]>({
    queryKey: ['servers'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/servers/`)
      if (!response.ok) {
        let detail = `HTTP ${response.status}`
        try {
          const err = await response.json()
          detail = typeof err?.detail === 'string' ? err.detail : JSON.stringify(err)
        } catch { /* JSON parse hatası yoksay */ }
        throw new Error(detail)
      }
      const data = await response.json()
      if (!Array.isArray(data)) throw new Error('API dizi döndürmedi')
      return data
    },
    refetchInterval: 60_000,   // 60 sn'de bir arka planda yenile
    placeholderData: (prev) => prev, // önceki veriyi göster, yüklenirken blank bırakma
  })

  // Tüm ONLINE sunucular için Node Exporter durumu iste (SSH yoksa backend Prometheus'tan bakar)
  const checkableServerIds = servers
    .filter(s => s.status === 'ONLINE')
    .map(s => s.id)
    .sort((a, b) => a - b)
    .join(',')

  // Node Exporter kurulu sunucuları listele
  // Node Exporter durumlarını ayrı bir query ile al (ONLINE sunucular; backend SSH + Prometheus fallback kullanır)
  const { data: nodeExporterStatuses = {} } = useQuery<Record<number, { installed: boolean; running: boolean }>>({
    queryKey: ['nodeExporterStatuses', checkableServerIds],
    queryFn: async () => {
      const onlineServers = servers.filter(s => s.status === 'ONLINE')
      if (onlineServers.length === 0) return {}

      const statusPromises = onlineServers.map(async (server) => {
        let installed = false
        let running = false
        try {
          const response = await fetch(`${API_BASE_URL}/monitoring/node-exporter/status/${server.id}`)
          const data = await response.json().catch(() => ({}))
          if (response.ok) {
            installed = Boolean(data.installed)
            running = Boolean(data.running)
          }
        } catch {
          // ağ/parse hatası
        }
        return {
          serverId: server.id,
          status: { installed, running }
        }
      })

      const results = await Promise.all(statusPromises)
      const statusMap: Record<number, { installed: boolean; running: boolean }> = {}
      results.forEach(r => { statusMap[r.serverId] = r.status })
      return statusMap
    },
    enabled: servers.length > 0 && checkableServerIds.length > 0,
    refetchInterval: 60000
  })

  const createMutation = useMutation({
    mutationFn: async (data: {
      name: string
      hostname: string
      ip_address: string
      status: string
      server_type: string
      os_type: string
      connection_config: Record<string, any>
    }) => {
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
      queryClient.invalidateQueries({ queryKey: ['nodeExporterStatuses'] })
      setShowAddModal(false)
      setFormData({
        name: '',
        hostname: '',
        ip_address: '',
        status: 'OFFLINE',
        server_type: 'VIRTUAL',
        os_type: 'linux',
        ssh_username: '',
        ssh_password: '',
        ssh_port: '22',
        sudo_password: '',
        private_key: ''
      })
    },
    onError: () => {
      // DEV: console.error(...)
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

  const INSTALL_REQUEST_TIMEOUT_MS = 120000

  const installNodeExporterMutation = useMutation({
    mutationFn: async (serverId: number) => {
      const controller = new AbortController()
      installAbortRef.current = controller
      const timeoutId = setTimeout(() => controller.abort(), INSTALL_REQUEST_TIMEOUT_MS)
      try {
        const response = await fetch(`${API_BASE_URL}/monitoring/node-exporter/install/${serverId}`, {
          method: 'POST',
          signal: controller.signal
        })
        const data = await response.json().catch(() => ({}))
        if (!response.ok) {
          setInstallingNodeExporter(null)
          setInstallResultByServerId(prev => ({
            ...prev,
            [serverId]: { success: false, error: data.detail || data.error || 'Kurulum başarısız', steps: Array.isArray(data.steps) ? data.steps : [] }
          }))
          throw new Error(data.detail || data.error || 'Failed to install Node Exporter')
        }
        return data
      } finally {
        clearTimeout(timeoutId)
        installAbortRef.current = null
      }
    },
    onSuccess: (data, serverId) => {
      queryClient.invalidateQueries({ queryKey: ['servers'] })
      queryClient.invalidateQueries({ queryKey: ['nodeExporterStatuses'] })
      setInstallingNodeExporter(null)
      setInstallSimulatedStep(prev => { const next = { ...prev }; delete next[serverId]; return next })
      const steps = Array.isArray(data.steps) ? data.steps : []
      setInstallResultByServerId(prev => ({ ...prev, [serverId]: { success: true, message: data.message, steps } }))
    },
    onError: (err: Error, serverId) => {
      setInstallingNodeExporter(null)
      setInstallSimulatedStep(prev => { const next = { ...prev }; delete next[serverId]; return next })
      const message = err.name === 'AbortError'
        ? 'Kurulum zaman aşımına uğradı (2 dk) veya iptal edildi. SSH/bağlantıyı kontrol edin.'
        : err.message
      setInstallResultByServerId(prev => ({ ...prev, [serverId]: { success: false, error: message, steps: [] } }))
    }
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    // DEV: console.log(...)
    if (!formData.name || formData.name.trim() === '') {
      alert('Sunucu adı gereklidir!')
      return
    }
    if (!formData.ip_address || formData.ip_address.trim() === '') {
      alert('IP adresi zorunludur! Lütfen sunucunun IP adresini girin.')
      return
    }
    const connection_config = formData.ssh_username
      ? {
          username: formData.ssh_username,
          password: formData.ssh_password || undefined,
          port: Number(formData.ssh_port || 22),
          sudo_password: formData.sudo_password || undefined,
          private_key: formData.private_key || undefined
        }
      : {}

    createMutation.mutate({
      name: formData.name,
      hostname: formData.hostname,
      ip_address: formData.ip_address,
      status: formData.status,
      server_type: formData.server_type,
      os_type: formData.os_type,
      connection_config
    })
  }

  const toggleSort = (key: string) => {
    if (sortKey === key) {
      setSortDirection(prev => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDirection('asc')
    }
  }

  const getSortIcon = (key: string) => {
    if (sortKey !== key) return '↕'
    return sortDirection === 'asc' ? '▲' : '▼'
  }

  const getStatusOrder = (status: string) => {
    const order: Record<string, number> = {
      ONLINE: 1,
      WARNING: 2,
      CRITICAL: 3,
      OFFLINE: 4
    }
    return order[status] ?? 5
  }

  const getNodeExporterOrder = (server: Server) => {
    const status = server.node_exporter
    if (status?.running) return 2
    if (status?.installed) return 1
    return 0
  }

  const parseIp = (ip: string) => ip.split('.').map(part => Number(part) || 0)

  // Sunuculara Node Exporter durumunu ekle
  const serversWithNodeExporter = servers.map(server => ({
    ...server,
    node_exporter: nodeExporterStatuses[server.id] || {
      installed: false,
      running: false
    }
  }))

  // Filtreleme
  const filteredServers = serversWithNodeExporter.filter(server => {
    const matchesSearch = server.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      server.ip_address?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      server.hostname?.toLowerCase().includes(searchTerm.toLowerCase())
    const matchesIp = !ipFilter || server.ip_address?.toLowerCase().includes(ipFilter.toLowerCase())
    
    // Status filtresi: showOffline true ise tümü, false ise sadece ONLINE
    const matchesStatus = showOffline 
      ? (statusFilter === 'all' || server.status === statusFilter)
      : (server.status === 'ONLINE' || (statusFilter !== 'all' && server.status === statusFilter))
    
    const matchesAiReady = aiReadyFilter === 'all' || 
      (aiReadyFilter === 'true' && server.ai_ready) ||
      (aiReadyFilter === 'false' && !server.ai_ready)
    
    const matchesType = typeFilter === 'all' || server.server_type === typeFilter

    const matchesNodeExporter = nodeExporterFilter === 'all' ||
      (nodeExporterFilter === 'installed' && server.node_exporter?.installed) ||
      (nodeExporterFilter === 'running' && server.node_exporter?.running) ||
      (nodeExporterFilter === 'not_installed' && !server.node_exporter?.installed)

    return matchesSearch && matchesIp && matchesStatus && matchesAiReady && matchesType && matchesNodeExporter
  })

  const sortedServers = [...filteredServers].sort((a, b) => {
    let aValue: number | string = ''
    let bValue: number | string = ''

    switch (sortKey) {
      case 'ip': {
        const aParts = parseIp(a.ip_address || '0.0.0.0')
        const bParts = parseIp(b.ip_address || '0.0.0.0')
        for (let i = 0; i < 4; i += 1) {
          if (aParts[i] !== bParts[i]) return sortDirection === 'asc' ? aParts[i] - bParts[i] : bParts[i] - aParts[i]
        }
        return 0
      }
      case 'status':
        aValue = getStatusOrder(a.status)
        bValue = getStatusOrder(b.status)
        break
      case 'type':
        aValue = a.server_type || ''
        bValue = b.server_type || ''
        break
      case 'cpu':
        aValue = a.cpu_cores || 0
        bValue = b.cpu_cores || 0
        break
      case 'memory':
        aValue = a.memory_gb || 0
        bValue = b.memory_gb || 0
        break
      case 'ai':
        aValue = a.ai_ready ? 1 : 0
        bValue = b.ai_ready ? 1 : 0
        break
      case 'node_exporter':
        aValue = getNodeExporterOrder(a)
        bValue = getNodeExporterOrder(b)
        break
      case 'name':
      default:
        aValue = a.name || ''
        bValue = b.name || ''
        break
    }

    if (typeof aValue === 'number' && typeof bValue === 'number') {
      return sortDirection === 'asc' ? aValue - bValue : bValue - aValue
    }
    return sortDirection === 'asc'
      ? String(aValue).localeCompare(String(bValue))
      : String(bValue).localeCompare(String(aValue))
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
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
        <p className="text-slate-400">Sunucular yükleniyor...</p>
      </div>
    )
  }

  if (isError && servers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4 p-6">
        <p className="text-red-400 font-medium">Sunucular yüklenemedi</p>
        <p className="text-slate-400 text-sm text-center max-w-md">
          {error instanceof Error ? error.message : 'Backend bağlantısını kontrol edin. API adresi: ' + API_BASE_URL}
        </p>
        <button
          onClick={() => refetch()}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg"
        >
          Tekrar dene
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Hata banner (eski veri varken hata alındıysa göster) */}
      {isError && servers.length > 0 && (
        <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-2.5 text-sm">
          <span className="text-red-400">⚠️ Yenileme hatası:</span>
          <span className="text-red-300">{error instanceof Error ? error.message : 'Bilinmeyen hata'}</span>
          <button onClick={() => refetch()} className="ml-auto text-xs text-red-400 underline">Tekrar dene</button>
        </div>
      )}
      {/* Arka plan yenileme göstergesi */}
      {isFetching && !isLoading && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <div className="animate-spin rounded-full h-3 w-3 border-b border-slate-400"></div>
          Yenileniyor...
        </div>
      )}
      {/* Header */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          <div className="flex flex-wrap items-center gap-3">
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
            {/* IP Filter */}
            <div className="relative">
              <input
                type="text"
                placeholder="IP filtre..."
                value={ipFilter}
                onChange={(e) => setIpFilter(e.target.value)}
                className="w-48 bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
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
            {/* Type Filter */}
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">Tüm Tipler</option>
              <option value="VIRTUAL">Virtual</option>
              <option value="PHYSICAL">Physical</option>
            </select>
            {/* Node Exporter Filter */}
            <select
              value={nodeExporterFilter}
              onChange={(e) => setNodeExporterFilter(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">Node Exporter: Tümü</option>
              <option value="running">Çalışıyor</option>
              <option value="installed">Kurulu</option>
              <option value="not_installed">Kurulu Değil</option>
            </select>

          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={async () => {
                try {
                  const response = await fetch(`${API_BASE_URL}/servers/check-health`, { method: 'POST' })
                  const data = await response.json()
                  if (response.ok) {
                    alert(`Durum kontrolü tamamlandı:\n${data.stats?.checked || 0} sunucu kontrol edildi\n${data.stats?.updated || 0} güncellendi`)
                    queryClient.invalidateQueries({ queryKey: ['servers'] })
                    queryClient.invalidateQueries({ queryKey: ['nodeExporterStatuses'] })
                  } else {
                    alert('Durum kontrolü başarısız: ' + (data.detail || 'Bilinmeyen hata'))
                  }
                } catch (err) {
                  alert('Durum kontrolü hatası: ' + (err instanceof Error ? err.message : 'Ağ hatası'))
                }
              }}
              className="inline-flex items-center px-4 py-2 bg-gradient-to-r from-green-600 to-green-700 text-white rounded-lg hover:from-green-500 hover:to-green-600 transition-all"
            >
              <span className="mr-2">🔄</span>
              Durumları Kontrol Et
            </button>
            <button
              onClick={() => setShowAddModal(true)}
              className="inline-flex items-center px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all shadow-lg shadow-blue-500/25"
            >
              <span className="mr-2">➕</span>
              Yeni Sunucu
            </button>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-900/50">
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <button onClick={() => toggleSort('name')} className="flex items-center gap-1">
                    Sunucu <span className="text-[10px]">{getSortIcon('name')}</span>
                  </button>
                </th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <button onClick={() => toggleSort('ip')} className="flex items-center gap-1">
                    IP Adresi <span className="text-[10px]">{getSortIcon('ip')}</span>
                  </button>
                </th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <button onClick={() => toggleSort('status')} className="flex items-center gap-1">
                    Durum <span className="text-[10px]">{getSortIcon('status')}</span>
                  </button>
                </th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <button onClick={() => toggleSort('type')} className="flex items-center gap-1">
                    Tip <span className="text-[10px]">{getSortIcon('type')}</span>
                  </button>
                </th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <div className="flex items-center gap-3">
                    <span>Kaynaklar</span>
                    <button onClick={() => toggleSort('cpu')} className="flex items-center gap-1">
                      CPU <span className="text-[10px]">{getSortIcon('cpu')}</span>
                    </button>
                    <button onClick={() => toggleSort('memory')} className="flex items-center gap-1">
                      RAM <span className="text-[10px]">{getSortIcon('memory')}</span>
                    </button>
                  </div>
                </th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <button onClick={() => toggleSort('ai')} className="flex items-center gap-1">
                    AI <span className="text-[10px]">{getSortIcon('ai')}</span>
                  </button>
                </th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <button onClick={() => toggleSort('node_exporter')} className="flex items-center gap-1">
                    Node Exporter <span className="text-[10px]">{getSortIcon('node_exporter')}</span>
                  </button>
                </th>
                <th className="px-6 py-4 text-right text-xs font-medium text-slate-400 uppercase tracking-wider">İşlemler</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700">
              {sortedServers.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-6 py-12 text-center text-slate-400">
                    <p className="font-medium">Henüz sunucu yok</p>
                    <p className="text-sm mt-1">Yeni sunucu eklemek için &quot;Yeni Sunucu&quot; butonunu kullanın veya backend/veritabanı bağlantısını kontrol edin.</p>
                    <p className="text-xs mt-2 text-slate-500">API: {API_BASE_URL}</p>
                  </td>
                </tr>
              ) : sortedServers.map((server) => (
                <React.Fragment key={server.id}>
                <tr className="hover:bg-slate-700/30 transition-colors">
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
                    {server.node_exporter?.running ? (
                      <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-green-500/20 text-green-400 border border-green-500/30">
                        ✅ Çalışıyor
                      </span>
                    ) : server.node_exporter?.installed ? (
                      <button
                        onClick={async () => {
                          setStartingNodeExporter(server.id)
                          try {
                            const response = await fetch(`${API_BASE_URL}/monitoring/node-exporter/start/${server.id}`, { method: 'POST' })
                            const data = await response.json().catch(() => ({}))
                            if (response.ok) {
                              queryClient.invalidateQueries({ queryKey: ['nodeExporterStatuses'] })
                              queryClient.invalidateQueries({ queryKey: ['servers'] })
                            } else {
                              alert('Başlatma hatası: ' + (data.detail || 'Bilinmeyen hata'))
                            }
                          } catch (e) {
                            alert('Hata: ' + (e instanceof Error ? e.message : String(e)))
                          } finally {
                            setStartingNodeExporter(null)
                          }
                        }}
                        disabled={startingNodeExporter === server.id}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 hover:bg-yellow-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Node Exporter Başlat"
                      >
                        {startingNodeExporter === server.id ? '⏳' : '▶️'} {startingNodeExporter === server.id ? 'Başlatılıyor...' : 'Başlat'}
                      </button>
                    ) : server.connection_config?.username ? (
                      <button
                        onClick={() => {
                          setInstallResultByServerId(prev => { const next = { ...prev }; delete next[server.id]; return next })
                          setInstallingNodeExporter(server.id)
                          installNodeExporterMutation.mutate(server.id)
                        }}
                        disabled={installingNodeExporter === server.id}
                        className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-blue-500/20 text-blue-400 border border-blue-500/30 hover:bg-blue-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Node Exporter Kur"
                      >
                        {installingNodeExporter === server.id ? '⏳ Kuruluyor...' : '📦 Kur'}
                      </button>
                    ) : (
                      <span className="text-slate-400 text-xs">SSH yok</span>
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
                {/* Kurulum adımları: Kur basılan satırda açılır */}
                {(installingNodeExporter === server.id || installResultByServerId[server.id]) && (
                  <tr key={`${server.id}-install`} className="bg-slate-800/80">
                    <td colSpan={8} className="px-6 py-4">
                      <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
                        <div className="flex items-center justify-between mb-3">
                          <span className="text-sm font-medium text-slate-300">Node Exporter kurulumu — {server.name}</span>
                          <div className="flex items-center gap-2">
                            {installingNodeExporter === server.id && (
                              <button
                                type="button"
                                onClick={() => { installAbortRef.current?.abort(); setInstallingNodeExporter(null) }}
                                className="text-xs px-2 py-1 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30 hover:bg-amber-500/30"
                              >
                                İptal
                              </button>
                            )}
                            <button
                              onClick={() => { installAbortRef.current?.abort(); setInstallingNodeExporter(null); setInstallResultByServerId(prev => { const next = { ...prev }; delete next[server.id]; return next }) }}
                              className="text-slate-400 hover:text-white text-xs"
                              aria-label="Kapat"
                            >
                              ✕ Kapat
                            </button>
                          </div>
                        </div>
                        <div className="mb-3">
                          <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                            {!installResultByServerId[server.id] ? (
                              <div
                                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                                style={{
                                  width: `${Math.min(100, ((installSimulatedStep[server.id] ?? -1) + 1) * (100 / 8))}%`
                                }}
                              />
                            ) : (
                              <div
                                className="h-full bg-green-500 rounded-full transition-all duration-500"
                                style={{
                                  width: `${installResultByServerId[server.id].steps?.length
                                    ? (installResultByServerId[server.id].steps!.filter(s => s.status === 'success' || s.status === 'skipped').length / Math.max(installResultByServerId[server.id].steps!.length, 1)) * 100
                                    : installResultByServerId[server.id].success ? 100 : 50}%`
                                }}
                              />
                            )}
                          </div>
                          <p className="text-slate-500 text-xs mt-1">
                            {!installResultByServerId[server.id]
                              ? 'Kurulum devam ediyor... (en fazla 2 dk; takılırsa İptal ile iptal edebilirsiniz)'
                              : installResultByServerId[server.id].success
                                ? 'Kurulum tamamlandı'
                                : 'Kurulum hata ile sonuçlandı'}
                          </p>
                        </div>
                        <div className="space-y-1.5 max-h-48 overflow-y-auto">
                          {(installResultByServerId[server.id]?.steps && installResultByServerId[server.id].steps!.length > 0
                            ? installResultByServerId[server.id].steps!
                            : NODE_EXPORTER_STEP_LABELS.map((s, i) => ({
                                ...s,
                                status: (i <= (installSimulatedStep[server.id] ?? -1) ? 'success' : 'pending') as string,
                                message: undefined as string | undefined
                              }))
                          ).map((step: { id: string; label: string; status: string; message?: string }) => (
                            <div key={step.id} className="flex items-center gap-2 py-1.5 px-2 rounded bg-slate-800/60 border border-slate-700/50">
                              <span className="flex-shrink-0 w-5 h-5 flex items-center justify-center text-xs">
                                {step.status === 'success' ? (
                                  <span className="text-green-400">✓</span>
                                ) : step.status === 'failed' ? (
                                  <span className="text-red-400">✕</span>
                                ) : step.status === 'skipped' ? (
                                  <span className="text-slate-500">−</span>
                                ) : (
                                  <span className="text-blue-400 animate-spin">⟳</span>
                                )}
                              </span>
                              <div className="flex-1 min-w-0">
                                <p className="text-slate-200 text-xs font-medium truncate">{step.label}</p>
                                {step.message && <p className="text-slate-500 text-[10px] truncate" title={step.message}>{step.message}</p>}
                              </div>
                            </div>
                          ))}
                        </div>
                        {installResultByServerId[server.id] && (
                          <div className={`mt-3 p-2 rounded border text-xs ${installResultByServerId[server.id].success ? 'bg-green-500/10 border-green-500/30 text-green-400' : 'bg-red-500/10 border-red-500/30 text-red-400'}`}>
                            {installResultByServerId[server.id].success
                              ? (installResultByServerId[server.id].message || 'Kurulum başarıyla tamamlandı.')
                              : (installResultByServerId[server.id].error || 'Kurulum sırasında bir hata oluştu.')}
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {sortedServers.length === 0 && (
          <div className="text-center py-12 text-slate-500">
            {searchTerm || ipFilter || statusFilter !== 'all' || aiReadyFilter !== 'all' || typeFilter !== 'all' || nodeExporterFilter !== 'all'
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
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  IP Adresi <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  value={formData.ip_address}
                  onChange={(e) => setFormData({ ...formData, ip_address: e.target.value })}
                  className={`w-full bg-slate-900 border rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent ${!formData.ip_address ? 'border-red-500/50' : 'border-slate-700'}`}
                  placeholder="örn: 192.168.1.100"
                />
                {!formData.ip_address && (
                  <p className="text-red-400 text-xs mt-1">IP adresi zorunludur</p>
                )}
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
              <div className="border-t border-slate-700 pt-4">
                <h3 className="text-sm font-semibold text-slate-200 mb-3">SSH Bilgileri (Node Exporter kurulumu için)</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">Kullanıcı Adı</label>
                    <input
                      type="text"
                      value={formData.ssh_username}
                      onChange={(e) => setFormData({ ...formData, ssh_username: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="örn: root"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">SSH Port</label>
                    <input
                      type="number"
                      value={formData.ssh_port}
                      onChange={(e) => setFormData({ ...formData, ssh_port: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="22"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4 mt-3">
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">Şifre</label>
                    <input
                      type="password"
                      value={formData.ssh_password}
                      onChange={(e) => setFormData({ ...formData, ssh_password: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="SSH şifresi"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">Sudo Şifresi</label>
                    <input
                      type="password"
                      value={formData.sudo_password}
                      onChange={(e) => setFormData({ ...formData, sudo_password: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="Opsiyonel"
                    />
                  </div>
                </div>
                <div className="mt-3">
                  <label className="block text-sm font-medium text-slate-300 mb-2">Private Key (opsiyonel)</label>
                  <textarea
                    value={formData.private_key}
                    onChange={(e) => setFormData({ ...formData, private_key: e.target.value })}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                    rows={3}
                  />
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
                <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
                  <p className="text-red-400 text-sm font-medium">Hata:</p>
                  <p className="text-red-300 text-sm mt-1">
                    {createMutation.error != null
                      ? (createMutation.error instanceof Error ? createMutation.error.message : String(createMutation.error))
                      : 'Bilinmeyen hata'}
                  </p>
                </div>
              )}
              {createMutation.isSuccess && (
                <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-3">
                  <p className="text-green-400 text-sm">✓ Sunucu başarıyla eklendi!</p>
                </div>
              )}
            </form>
          </div>
        </div>
      )}

    </div>
  )
}

export default Servers

