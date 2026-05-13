import React, { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { API_BASE_URL } from '../config/api'
import { ServerDetailDrawer } from './Servers'

interface DashboardServer {
  id: number
  name: string
  hostname: string
  ip_address: string
  status: string
  ai_ready: boolean
  cpu_cores: number
  memory_gb: number
  os_type: string
  os_version?: string
  server_type?: string
  connection_config?: any
  node_exporter?: { installed: boolean; running: boolean }
  created_at?: string
}

interface Hypervisor {
  id: number
  name: string
  type: string
  ip_address: string
}

interface EsxHost {
  host_name: string
  host_ref?: string
  last_updated?: string
  cpu_usage_pct: number | null
  cpu_usage_mhz: number | null
  cpu_total_mhz: number | null
  cpu_cores: number | null
  mem_used_mb: number | null
  mem_total_mb: number | null
  mem_usage_pct: number | null
  ds_used_gb: number | null
  ds_total_gb: number | null
  ds_usage_pct: number | null
  vms_running: number | null
  vms_total: number | null
  connection_state: string | null
  power_state: string | null
  maintenance_mode: number | null
}

interface EsxHostMetricsResponse {
  hypervisor_id: number
  hypervisor_name: string
  host_count: number
  hosts: EsxHost[]
}

// ── Yardımcı bileşenler ────────────────────────────────────────────────────

function UsageBar({
  pct,
  used,
  total,
  unit,
  colorClass,
}: {
  pct: number | null
  used: number | null
  total: number | null
  unit: string
  colorClass: string
}) {
  const p = pct ?? (used != null && total != null && total > 0 ? (used / total) * 100 : null)
  if (p == null) return <span className="text-slate-500 text-xs">Veri yok</span>

  const freeVal = total != null && used != null ? total - used : null
  const barColor =
    p >= 90 ? 'bg-red-500' : p >= 75 ? 'bg-yellow-500' : colorClass

  return (
    <div className="w-full">
      <div className="flex justify-between text-xs mb-1">
        <span className={p >= 90 ? 'text-red-400' : p >= 75 ? 'text-yellow-400' : 'text-slate-300'}>
          {p.toFixed(1)}% dolu
        </span>
        {freeVal != null && (
          <span className="text-slate-400">
            {freeVal >= 1024 && unit === 'MB'
              ? `${(freeVal / 1024).toFixed(1)} GB boş`
              : freeVal >= 1024 && unit === 'GB'
              ? `${(freeVal / 1024).toFixed(1)} TB boş`
              : `${freeVal % 1 === 0 ? freeVal : freeVal.toFixed(1)} ${unit} boş`}
          </span>
        )}
      </div>
      <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-full ${barColor} rounded-full transition-all duration-500`}
          style={{ width: `${Math.min(p, 100)}%` }}
        />
      </div>
    </div>
  )
}

function EsxResourcePanel({ hypervisors }: { hypervisors: Hypervisor[] }) {
  const vmwareHvs = hypervisors.filter(hv => hv.type?.toLowerCase() === 'vmware')
  const [allHosts, setAllHosts] = useState<{ hvName: string; host: EsxHost }[]>([])
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    if (vmwareHvs.length === 0) { setIsLoading(false); return }
    setIsLoading(true)
    Promise.all(
      vmwareHvs.map(hv =>
        fetch(`${API_BASE_URL}/hypervisors/${hv.id}/host-metrics`)
          .then(r => r.ok ? r.json() : null)
          .then((data: EsxHostMetricsResponse | null) =>
            (data?.hosts || []).map(h => ({ hvName: hv.name, host: h }))
          )
          .catch(() => [] as { hvName: string; host: EsxHost }[])
      )
    ).then(results => {
      setAllHosts(results.flat())
      setIsLoading(false)
    })
    const interval = setInterval(() => {
      Promise.all(
        vmwareHvs.map(hv =>
          fetch(`${API_BASE_URL}/hypervisors/${hv.id}/host-metrics`)
            .then(r => r.ok ? r.json() : null)
            .then((data: EsxHostMetricsResponse | null) =>
              (data?.hosts || []).map(h => ({ hvName: hv.name, host: h }))
            )
            .catch(() => [] as { hvName: string; host: EsxHost }[])
        )
      ).then(results => setAllHosts(results.flat()))
    }, 15 * 60 * 1000)
    return () => clearInterval(interval)
  }, [hypervisors.map(h => h.id).join(',')])

  const hasData = allHosts.length > 0

  if (vmwareHvs.length === 0) return null

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-blue-600 flex items-center justify-center">
            <span className="text-base">🖧</span>
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">ESX Host Kaynak Durumu</h2>
            <p className="text-slate-400 text-xs mt-0.5">15 dakikada bir güncellenir</p>
          </div>
        </div>
        {isLoading && (
          <div className="flex items-center gap-2 text-slate-400 text-xs">
            <div className="animate-spin rounded-full h-3.5 w-3.5 border-b border-slate-400" />
            Yükleniyor...
          </div>
        )}
      </div>

      {!hasData && !isLoading ? (
        <div className="px-6 py-10 text-center text-slate-500 text-sm">
          Henüz ESX host metrik verisi yok. İlk veri 15 dakika içinde toplanacak.
          <br />
          <span className="text-slate-600 text-xs">Manuel sync için: Hypervisor &gt; host-metrics/sync</span>
        </div>
      ) : (
        <div className="divide-y divide-slate-700/60">
          {allHosts.map(({ hvName, host }) => {
            const inMaint = host.maintenance_mode === 1
            const disconnected = host.connection_state === 'disconnected' || host.connection_state === 'notResponding'
            const shortName = host.host_name.split('.')[0]

            return (
              <div
                key={`${hvName}-${host.host_name}`}
                className={`px-6 py-4 hover:bg-slate-700/30 transition-colors ${disconnected ? 'opacity-60' : ''}`}
              >
                {/* Host başlık satırı */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-white font-medium text-sm">{shortName}</span>
                    <span className="text-slate-500 text-xs hidden sm:inline">{hvName}</span>
                    {inMaint && (
                      <span className="px-1.5 py-0.5 rounded text-xs bg-yellow-500/20 text-yellow-400 border border-yellow-500/30">
                        Bakım
                      </span>
                    )}
                    {disconnected && (
                      <span className="px-1.5 py-0.5 rounded text-xs bg-red-500/20 text-red-400 border border-red-500/30">
                        Bağlantı Yok
                      </span>
                    )}
                  </div>
                  {(host.vms_running != null || host.vms_total != null) && (
                    <span className="text-slate-400 text-xs">
                      {host.vms_running ?? '?'} / {host.vms_total ?? '?'} VM çalışıyor
                    </span>
                  )}
                </div>

                {/* 3 sütun: CPU / RAM / Disk */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  {/* CPU */}
                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                      <span className="font-medium">CPU</span>
                      <span>
                        {host.cpu_total_mhz != null
                          ? `${host.cpu_total_mhz >= 1000
                              ? (host.cpu_total_mhz / 1000).toFixed(1) + ' GHz'
                              : host.cpu_total_mhz + ' MHz'} toplam`
                          : host.cpu_cores != null ? `${host.cpu_cores} core` : ''}
                      </span>
                    </div>
                    <UsageBar
                      pct={host.cpu_usage_pct}
                      used={host.cpu_usage_mhz}
                      total={host.cpu_total_mhz}
                      unit="MHz"
                      colorClass="bg-blue-500"
                    />
                    {host.cpu_total_mhz != null && host.cpu_usage_mhz != null && (
                      <p className="text-xs text-slate-500">
                        {((host.cpu_total_mhz - host.cpu_usage_mhz) >= 1000
                          ? ((host.cpu_total_mhz - host.cpu_usage_mhz) / 1000).toFixed(1) + ' GHz'
                          : (host.cpu_total_mhz - host.cpu_usage_mhz).toFixed(0) + ' MHz')}{' '}
                        boş kapasite
                      </p>
                    )}
                  </div>

                  {/* RAM */}
                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                      <span className="font-medium">RAM</span>
                      <span>
                        {host.mem_total_mb != null
                          ? `${(host.mem_total_mb / 1024).toFixed(0)} GB toplam`
                          : ''}
                      </span>
                    </div>
                    <UsageBar
                      pct={host.mem_usage_pct}
                      used={host.mem_used_mb != null ? host.mem_used_mb / 1024 : null}
                      total={host.mem_total_mb != null ? host.mem_total_mb / 1024 : null}
                      unit="GB"
                      colorClass="bg-purple-500"
                    />
                    {host.mem_total_mb != null && host.mem_used_mb != null && (
                      <p className="text-xs text-slate-500">
                        {((host.mem_total_mb - host.mem_used_mb) / 1024).toFixed(1)} GB boş kapasite
                      </p>
                    )}
                  </div>

                  {/* Disk */}
                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                      <span className="font-medium">Datastore</span>
                      <span>
                        {host.ds_total_gb != null
                          ? `${host.ds_total_gb >= 1024
                              ? (host.ds_total_gb / 1024).toFixed(1) + ' TB'
                              : host.ds_total_gb.toFixed(0) + ' GB'} toplam`
                          : ''}
                      </span>
                    </div>
                    <UsageBar
                      pct={host.ds_usage_pct}
                      used={host.ds_used_gb}
                      total={host.ds_total_gb}
                      unit="GB"
                      colorClass="bg-emerald-500"
                    />
                    {host.ds_total_gb != null && host.ds_used_gb != null && (
                      <p className="text-xs text-slate-500">
                        {(host.ds_total_gb - host.ds_used_gb) >= 1024
                          ? ((host.ds_total_gb - host.ds_used_gb) / 1024).toFixed(1) + ' TB'
                          : (host.ds_total_gb - host.ds_used_gb).toFixed(1) + ' GB'}{' '}
                        boş kapasite
                      </p>
                    )}
                  </div>
                </div>

                {/* Özet sayı badge'leri */}
                <div className="flex flex-wrap gap-2 mt-3">
                  {host.cpu_usage_pct != null && (
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium border
                      ${host.cpu_usage_pct >= 90
                        ? 'bg-red-500/15 text-red-400 border-red-500/30'
                        : host.cpu_usage_pct >= 75
                        ? 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30'
                        : 'bg-blue-500/15 text-blue-400 border-blue-500/30'}`}>
                      CPU {host.cpu_usage_pct.toFixed(1)}%
                    </span>
                  )}
                  {host.mem_usage_pct != null && (
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium border
                      ${host.mem_usage_pct >= 90
                        ? 'bg-red-500/15 text-red-400 border-red-500/30'
                        : host.mem_usage_pct >= 75
                        ? 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30'
                        : 'bg-purple-500/15 text-purple-400 border-purple-500/30'}`}>
                      RAM {host.mem_usage_pct.toFixed(1)}%
                    </span>
                  )}
                  {host.ds_usage_pct != null && (
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium border
                      ${host.ds_usage_pct >= 90
                        ? 'bg-red-500/15 text-red-400 border-red-500/30'
                        : host.ds_usage_pct >= 75
                        ? 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30'
                        : 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'}`}>
                      Disk {host.ds_usage_pct.toFixed(1)}%
                    </span>
                  )}
                  {host.last_updated && (
                    <span className="px-2 py-0.5 rounded-full text-xs text-slate-500 border border-slate-700">
                      {new Date(host.last_updated).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

const Dashboard: React.FC = () => {
  const [selectedServer, setSelectedServer] = useState<DashboardServer | null>(null)
  const { data: servers = [], isLoading: serversLoading } = useQuery<DashboardServer[]>({
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

  return (    <>

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

      {/* ESX Host Kaynak Doluluk Paneli — stats'ın hemen altında */}
      {hypervisors.some(hv => hv.type?.toLowerCase() === 'vmware') && (
        <EsxResourcePanel hypervisors={hypervisors} />
      )}

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
                <div key={server.id} className="px-6 py-4 hover:bg-slate-700/50 transition-colors cursor-pointer" onClick={() => setSelectedServer(server)}>
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

      {/* Hypervisors — küçük özet kartlar */}
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

      {selectedServer && (
        <ServerDetailDrawer server={selectedServer as any} onClose={() => setSelectedServer(null)} />
      )}
    </>
  )
}

export default Dashboard