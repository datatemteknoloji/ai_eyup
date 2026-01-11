import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

const API_BASE_URL = 'http://192.168.1.166:8000/api/v1'

interface Server {
  id: number
  name: string
  hostname: string
  ip_address: string
  status: string
  ai_ready: boolean
  cpu_cores: number
  memory_gb: number
  os_type: string
  created_at?: string
}

interface Hypervisor {
  id: number
  name: string
  type: string
  ip_address: string
}

const Dashboard: React.FC = () => {
  const { data: servers = [], isLoading: serversLoading } = useQuery<Server[]>({
    queryKey: ['servers'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/servers/`)
      if (!response.ok) throw new Error('Failed to fetch servers')
      return response.json()
    }
  })

  const { data: hypervisors = [], isLoading: hypervisorsLoading } = useQuery<Hypervisor[]>({
    queryKey: ['hypervisors'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/hypervisors/`)
      if (!response.ok) throw new Error('Failed to fetch hypervisors')
      return response.json()
    }
  })

  if (serversLoading || hypervisorsLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    )
  }

  // İstatistikler
  const totalServers = servers.length
  const onlineServers = servers.filter(s => s.status === 'ONLINE').length
  const offlineServers = servers.filter(s => s.status === 'OFFLINE').length
  const warningServers = servers.filter(s => s.status === 'WARNING').length
  const criticalServers = servers.filter(s => s.status === 'CRITICAL').length
  const aiReadyServers = servers.filter(s => s.ai_ready).length
  const totalCpu = servers.reduce((sum, s) => sum + (s.cpu_cores || 0), 0)
  const totalRam = servers.reduce((sum, s) => sum + (s.memory_gb || 0), 0)

  const stats = [
    { label: 'Toplam Sunucu', value: totalServers, icon: '🖥️', color: 'from-blue-500 to-blue-600' },
    { label: 'Çevrimiçi', value: onlineServers, icon: '✅', color: 'from-green-500 to-green-600' },
    { label: 'Çevrimdışı', value: offlineServers, icon: '⭕', color: 'from-slate-500 to-slate-600' },
    { label: 'AI Ready', value: aiReadyServers, icon: '🤖', color: 'from-purple-500 to-purple-600' },
    { label: 'Hypervisor', value: hypervisors.length, icon: '☁️', color: 'from-indigo-500 to-indigo-600' },
    { label: 'Toplam CPU', value: `${totalCpu}`, icon: '⚙️', color: 'from-orange-500 to-orange-600' },
    { label: 'Toplam RAM', value: `${totalRam} GB`, icon: '💾', color: 'from-pink-500 to-pink-600' },
    { label: 'Uyarı', value: warningServers + criticalServers, icon: '⚠️', color: 'from-yellow-500 to-yellow-600' },
  ]

  // Son online sunucular
  const recentOnline = servers
    .filter(s => s.status === 'ONLINE')
    .slice(0, 5)

  return (
    <div className="space-y-6">
      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat, index) => (
          <div
            key={index}
            className="bg-slate-800 rounded-xl p-5 border border-slate-700 hover:border-slate-600 transition-all duration-200 hover:shadow-lg hover:shadow-slate-900/50"
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-slate-400 text-sm">{stat.label}</p>
                <p className="text-2xl font-bold text-white mt-1">{stat.value}</p>
              </div>
              <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${stat.color} flex items-center justify-center shadow-lg`}>
                <span className="text-2xl">{stat.icon}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Durum Dağılımı */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-700">
            <h2 className="text-lg font-semibold text-white">Sunucu Durumu</h2>
          </div>
          <div className="p-6 space-y-4">
            {/* Progress Bars */}
            <div>
              <div className="flex justify-between text-sm mb-2">
                <span className="text-slate-400">Çevrimiçi</span>
                <span className="text-green-400 font-medium">{onlineServers} / {totalServers}</span>
              </div>
              <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-green-500 to-green-400 rounded-full transition-all duration-500"
                  style={{ width: `${totalServers > 0 ? (onlineServers / totalServers) * 100 : 0}%` }}
                />
              </div>
            </div>
            <div>
              <div className="flex justify-between text-sm mb-2">
                <span className="text-slate-400">Çevrimdışı</span>
                <span className="text-slate-400 font-medium">{offlineServers} / {totalServers}</span>
              </div>
              <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-slate-500 to-slate-400 rounded-full transition-all duration-500"
                  style={{ width: `${totalServers > 0 ? (offlineServers / totalServers) * 100 : 0}%` }}
                />
              </div>
            </div>
            {(warningServers > 0 || criticalServers > 0) && (
              <div>
                <div className="flex justify-between text-sm mb-2">
                  <span className="text-slate-400">Uyarı/Kritik</span>
                  <span className="text-yellow-400 font-medium">{warningServers + criticalServers} / {totalServers}</span>
                </div>
                <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-yellow-500 to-red-500 rounded-full transition-all duration-500"
                    style={{ width: `${totalServers > 0 ? ((warningServers + criticalServers) / totalServers) * 100 : 0}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Çevrimiçi Sunucular */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Çevrimiçi Sunucular</h2>
            <Link to="/servers" className="text-blue-400 hover:text-blue-300 text-sm">
              Tümünü Gör →
            </Link>
          </div>
          <div className="divide-y divide-slate-700">
            {recentOnline.length > 0 ? (
              recentOnline.map((server) => (
                <div key={server.id} className="px-6 py-4 hover:bg-slate-700/50 transition-colors">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-3">
                      <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-green-500 to-green-600 flex items-center justify-center">
                        <span className="text-white text-lg">🖥️</span>
                      </div>
                      <div>
                        <p className="text-white font-medium">{server.name}</p>
                        <p className="text-slate-400 text-sm">{server.ip_address || server.hostname}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-green-500/20 text-green-400 border border-green-500/30">
                        ● ONLINE
                      </span>
                      {server.ai_ready && (
                        <span className="ml-2 inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-purple-500/20 text-purple-400 border border-purple-500/30">
                          AI
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="px-6 py-8 text-center text-slate-500">
                Çevrimiçi sunucu bulunamadı
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Hypervisors */}
      {hypervisors.length > 0 && (
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Hypervisor'lar</h2>
            <Link to="/hypervisors" className="text-blue-400 hover:text-blue-300 text-sm">
              Tümünü Gör →
            </Link>
          </div>
          <div className="p-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {hypervisors.map((hv) => (
              <div key={hv.id} className="bg-slate-700/50 rounded-lg p-4 border border-slate-600 hover:border-slate-500 transition-colors">
                <div className="flex items-center space-x-3">
                  <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-indigo-500 to-indigo-600 flex items-center justify-center">
                    <span className="text-white text-lg">☁️</span>
                  </div>
                  <div>
                    <p className="text-white font-medium">{hv.name}</p>
                    <p className="text-slate-400 text-sm">{hv.type.toUpperCase()} • {hv.ip_address}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default Dashboard
