import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

const API_BASE_URL = 'http://192.168.1.166:8000/api/v1'

interface Server {
  id: number
  name: string
  status: string
  ai_ready: boolean
  cpu_cores: number
  memory_gb: number
  created_at?: string
}

interface Hypervisor {
  id: number
  name: string
  type: string
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
    return <div className="text-center py-8">Yükleniyor...</div>
  }

  // İstatistikleri hesapla
  const totalServers = servers.length
  const onlineServers = servers.filter(s => s.status === 'ONLINE').length
  const offlineServers = servers.filter(s => s.status === 'OFFLINE').length
  const warningServers = servers.filter(s => s.status === 'WARNING').length
  const criticalServers = servers.filter(s => s.status === 'CRITICAL').length
  const aiReadyServers = servers.filter(s => s.ai_ready).length
  const totalHypervisors = hypervisors.length
  const totalCpuCores = servers.reduce((sum, s) => sum + (s.cpu_cores || 0), 0)
  const totalMemory = servers.reduce((sum, s) => sum + (s.memory_gb || 0), 0)

  const stats = [
    {
      name: 'Toplam Sunucu',
      value: totalServers,
      icon: '🖥️',
      color: 'bg-blue-500',
      link: '/servers'
    },
    {
      name: 'Çevrimiçi',
      value: onlineServers,
      icon: '✅',
      color: 'bg-green-500',
      link: '/servers'
    },
    {
      name: 'Çevrimdışı',
      value: offlineServers,
      icon: '❌',
      color: 'bg-gray-500',
      link: '/servers'
    },
    {
      name: 'AI Ready',
      value: aiReadyServers,
      icon: '🤖',
      color: 'bg-purple-500',
      link: '/servers'
    },
    {
      name: 'Hypervisor',
      value: totalHypervisors,
      icon: '☁️',
      color: 'bg-indigo-500',
      link: '/hypervisors'
    },
    {
      name: 'Toplam CPU',
      value: `${totalCpuCores} Core`,
      icon: '⚙️',
      color: 'bg-yellow-500',
      link: '/servers'
    },
    {
      name: 'Toplam RAM',
      value: `${totalMemory} GB`,
      icon: '💾',
      color: 'bg-pink-500',
      link: '/servers'
    },
    {
      name: 'Uyarı',
      value: warningServers,
      icon: '⚠️',
      color: 'bg-yellow-500',
      link: '/servers'
    }
  ]

  // Son eklenen sunucular (ID'ye göre sırala - yeni eklenenler genelde daha yüksek ID'ye sahip)
  const recentServers = [...servers]
    .sort((a, b) => {
      // created_at varsa ona göre, yoksa ID'ye göre sırala
      if (a.created_at && b.created_at) {
        const dateA = new Date(a.created_at).getTime()
        const dateB = new Date(b.created_at).getTime()
        return dateB - dateA
      }
      return b.id - a.id
    })
    .slice(0, 5)

  return (
    <div className="px-4 sm:px-6 lg:px-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Dashboard</h1>
        <p className="mt-2 text-sm text-gray-700">Sistem genel bakış ve istatistikler</p>
      </div>

      {/* İstatistik Kartları */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4 mb-8">
        {stats.map((stat) => (
          <Link
            key={stat.name}
            to={stat.link}
            className="bg-white overflow-hidden shadow rounded-lg hover:shadow-md transition-shadow"
          >
            <div className="p-5">
              <div className="flex items-center">
                <div className={`${stat.color} rounded-md p-3`}>
                  <span className="text-2xl">{stat.icon}</span>
                </div>
                <div className="ml-5 w-0 flex-1">
                  <dl>
                    <dt className="text-sm font-medium text-gray-500 truncate">{stat.name}</dt>
                    <dd className="text-lg font-semibold text-gray-900">{stat.value}</dd>
                  </dl>
                </div>
              </div>
            </div>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Durum Dağılımı */}
        <div className="bg-white shadow rounded-lg">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-medium text-gray-900">Sunucu Durum Dağılımı</h2>
          </div>
          <div className="p-6">
            <div className="space-y-4">
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-gray-600">Çevrimiçi</span>
                  <span className="font-medium">{onlineServers} / {totalServers}</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div
                    className="bg-green-500 h-2 rounded-full"
                    style={{ width: `${totalServers > 0 ? (onlineServers / totalServers) * 100 : 0}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-gray-600">Çevrimdışı</span>
                  <span className="font-medium">{offlineServers} / {totalServers}</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div
                    className="bg-gray-500 h-2 rounded-full"
                    style={{ width: `${totalServers > 0 ? (offlineServers / totalServers) * 100 : 0}%` }}
                  />
                </div>
              </div>
              {warningServers > 0 && (
                <div>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-gray-600">Uyarı</span>
                    <span className="font-medium">{warningServers} / {totalServers}</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="bg-yellow-500 h-2 rounded-full"
                      style={{ width: `${totalServers > 0 ? (warningServers / totalServers) * 100 : 0}%` }}
                    />
                  </div>
                </div>
              )}
              {criticalServers > 0 && (
                <div>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-gray-600">Kritik</span>
                    <span className="font-medium">{criticalServers} / {totalServers}</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="bg-red-500 h-2 rounded-full"
                      style={{ width: `${totalServers > 0 ? (criticalServers / totalServers) * 100 : 0}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Son Eklenen Sunucular */}
        <div className="bg-white shadow rounded-lg">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-medium text-gray-900">Son Eklenen Sunucular</h2>
          </div>
          <div className="p-6">
            {recentServers.length > 0 ? (
              <ul className="divide-y divide-gray-200">
                {recentServers.map((server) => (
                  <li key={server.id} className="py-3">
                    <div className="flex items-center justify-between">
                      <div className="flex-1">
                        <p className="text-sm font-medium text-gray-900">{server.name}</p>
                        <p className="text-sm text-gray-500">
                          {server.cpu_cores > 0 && `${server.cpu_cores} CPU`}
                          {server.memory_gb > 0 && ` • ${server.memory_gb}GB RAM`}
                        </p>
                      </div>
                      <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                        server.status === 'ONLINE' ? 'bg-green-100 text-green-800' :
                        server.status === 'OFFLINE' ? 'bg-gray-100 text-gray-800' :
                        server.status === 'WARNING' ? 'bg-yellow-100 text-yellow-800' :
                        'bg-red-100 text-red-800'
                      }`}>
                        {server.status}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-gray-500">Henüz sunucu eklenmemiş</p>
            )}
          </div>
          <div className="px-6 py-4 border-t border-gray-200 bg-gray-50">
            <Link
              to="/servers"
              className="text-sm font-medium text-blue-600 hover:text-blue-500"
            >
              Tüm sunucuları görüntüle →
            </Link>
          </div>
        </div>
      </div>

      {/* Hypervisor Listesi */}
      {totalHypervisors > 0 && (
        <div className="mt-6 bg-white shadow rounded-lg">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-medium text-gray-900">Hypervisor'lar</h2>
          </div>
          <div className="p-6">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {hypervisors.map((hypervisor) => (
                <div key={hypervisor.id} className="border rounded-lg p-4">
                  <h3 className="text-sm font-medium text-gray-900">{hypervisor.name}</h3>
                  <p className="mt-1 text-sm text-gray-500">{hypervisor.type.toUpperCase()}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="px-6 py-4 border-t border-gray-200 bg-gray-50">
            <Link
              to="/hypervisors"
              className="text-sm font-medium text-blue-600 hover:text-blue-500"
            >
              Tüm hypervisor'ları görüntüle →
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}

export default Dashboard
