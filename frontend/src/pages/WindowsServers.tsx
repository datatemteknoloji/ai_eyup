import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Wifi, WifiOff, RefreshCw, Settings, Activity,
  Shield, Cpu, MemoryStick, Download, Play, Square, RotateCcw,
  Search, X, CheckCircle, XCircle } from 'lucide-react'
import { API_BASE_URL } from '../config/api'

const WIN_API = `${API_BASE_URL}/windows`

// ── Types ─────────────────────────────────────────────────────────────────────

interface WindowsServer {
  id: number
  name: string
  hostname: string
  ip_address: string
  status: string
  os_type: string
  cpu_cores: number
  memory_gb: number
  hypervisor_id: number | null
  hypervisor_name: string | null
  winrm_configured: boolean
  winrm_port: number
}

interface ServiceItem {
  Name: string
  DisplayName: string
  Status: string
  StartType: string
}

interface EventLogEntry {
  TimeCreated: string
  LevelDisplayName: string
  Id: number
  ProviderName: string
  Message: string
}

interface UpdateItem {
  Title: string
  KB: string
  Severity: string
  Mandatory: boolean
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const statusBadge = (status: string) => {
  if (status === 'ONLINE') return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-500/15 text-green-400 border border-green-500/30">
      <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" /> Aktif
    </span>
  )
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-500/15 text-slate-400 border border-slate-600/40">
      <span className="w-1.5 h-1.5 bg-slate-500 rounded-full" /> Çevrimdışı
    </span>
  )
}

const levelColor = (level: string) => {
  const l = level?.toLowerCase()
  if (l?.includes('critical') || l?.includes('error')) return 'text-red-400'
  if (l?.includes('warning')) return 'text-yellow-400'
  return 'text-slate-400'
}

// ── Credential Modal ──────────────────────────────────────────────────────────

const CredentialModal: React.FC<{ serverId: number; onClose: () => void }> = ({ serverId, onClose }) => {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({ username: '', password: '', port: 5985, use_https: false })
  const [result, setResult] = useState<any>(null)

  const save = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${WIN_API}/servers/${serverId}/save-credentials`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      return r.json()
    },
    onSuccess: (data) => {
      setResult(data)
      queryClient.invalidateQueries({ queryKey: ['windows-servers'] })
    },
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-800 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-white font-semibold">WinRM Kimlik Bilgileri</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={18} /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-slate-400 mb-1 block">Kullanıcı Adı (DOMAIN\\user veya user)</label>
            <input value={form.username} onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
              className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Administrator" />
          </div>
          <div>
            <label className="text-xs text-slate-400 mb-1 block">Parola</label>
            <input type="password" value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
              className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="••••••••" />
          </div>
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="text-xs text-slate-400 mb-1 block">Port</label>
              <input type="number" value={form.port} onChange={e => setForm(f => ({ ...f, port: Number(e.target.value) }))}
                className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div className="flex items-end pb-2 gap-2">
              <input type="checkbox" id="https" checked={form.use_https} onChange={e => setForm(f => ({ ...f, use_https: e.target.checked }))}
                className="w-4 h-4 rounded" />
              <label htmlFor="https" className="text-xs text-slate-300">HTTPS</label>
            </div>
          </div>
          {result && (
            <div className={`rounded-lg p-3 text-sm ${result.connection_test?.connected ? 'bg-green-500/10 border border-green-500/30 text-green-300' : 'bg-red-500/10 border border-red-500/30 text-red-300'}`}>
              {result.connection_test?.connected ? '✓ Bağlantı başarılı' : `✗ ${result.connection_test?.message || 'Bağlantı başarısız'}`}
            </div>
          )}
          <button
            onClick={() => save.mutate()}
            disabled={save.isPending || !form.username || !form.password}
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg font-medium text-sm transition-colors"
          >
            {save.isPending ? 'Kaydediliyor...' : 'Kaydet & Test Et'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Server Detail Panel ───────────────────────────────────────────────────────

const ServerDetail: React.FC<{ server: WindowsServer; onClose: () => void }> = ({ server, onClose }) => {
  const [tab, setTab] = useState<'info' | 'services' | 'events' | 'updates' | 'exporter'>('info')
  const [logChannel, setLogChannel] = useState('System')
  const [serviceSearch, setServiceSearch] = useState('')
  const queryClient = useQueryClient()

  const infoQ = useQuery({
    queryKey: ['win-info', server.id],
    queryFn: async () => {
      const r = await fetch(`${WIN_API}/servers/${server.id}/info`)
      if (!r.ok) throw new Error('Bilgi alınamadı')
      return r.json()
    },
    enabled: tab === 'info' && server.winrm_configured,
  })

  const perfQ = useQuery({
    queryKey: ['win-perf', server.id],
    queryFn: async () => {
      const r = await fetch(`${WIN_API}/servers/${server.id}/performance`)
      return r.json()
    },
    enabled: tab === 'info' && server.winrm_configured,
    refetchInterval: 30000,
  })

  const servicesQ = useQuery({
    queryKey: ['win-services', server.id],
    queryFn: async () => {
      const r = await fetch(`${WIN_API}/servers/${server.id}/services`)
      return r.json() as Promise<ServiceItem[]>
    },
    enabled: tab === 'services' && server.winrm_configured,
  })

  const eventsQ = useQuery({
    queryKey: ['win-events', server.id, logChannel],
    queryFn: async () => {
      const r = await fetch(`${WIN_API}/servers/${server.id}/event-logs?log_name=${logChannel}&count=50`)
      return r.json() as Promise<EventLogEntry[]>
    },
    enabled: tab === 'events' && server.winrm_configured,
  })

  const updatesQ = useQuery({
    queryKey: ['win-updates', server.id],
    queryFn: async () => {
      const r = await fetch(`${WIN_API}/servers/${server.id}/updates`)
      return r.json()
    },
    enabled: tab === 'updates' && server.winrm_configured,
  })

  const exporterQ = useQuery({
    queryKey: ['win-exporter', server.id],
    queryFn: async () => {
      const r = await fetch(`${WIN_API}/servers/${server.id}/exporter/status`)
      return r.json()
    },
    enabled: tab === 'exporter' && server.winrm_configured,
  })

  const svcAction = useMutation({
    mutationFn: async ({ name, action }: { name: string; action: string }) => {
      const r = await fetch(`${WIN_API}/servers/${server.id}/services/${name}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      })
      return r.json()
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['win-services', server.id] }),
  })

  const installExporter = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${WIN_API}/servers/${server.id}/exporter/install`, { method: 'POST' })
      return r.json()
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['win-exporter', server.id] }),
  })

  const installAllUpdates = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${WIN_API}/servers/${server.id}/updates/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_reboot: false }),
      })
      return r.json()
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['win-updates', server.id] }),
  })

  const filteredServices = (servicesQ.data || []).filter(s =>
    !serviceSearch || s.DisplayName?.toLowerCase().includes(serviceSearch.toLowerCase()) ||
    s.Name?.toLowerCase().includes(serviceSearch.toLowerCase())
  )

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="w-full max-w-2xl bg-slate-800 border-l border-slate-700 flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-700">
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${server.status === 'ONLINE' ? 'bg-blue-500/20' : 'bg-slate-700'}`}>
            <span className="text-[10px] font-bold text-blue-400">WIN</span>
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-white font-semibold truncate">{server.name}</h2>
            <p className="text-slate-400 text-xs font-mono">{server.ip_address}</p>
          </div>
          {statusBadge(server.status)}
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none ml-2">&times;</button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-slate-700 bg-slate-800/60 overflow-x-auto">
          {[
            ['info', 'Sistem'],
            ['services', 'Servisler'],
            ['events', 'Event Log'],
            ['updates', 'Güncellemeler'],
            ['exporter', 'Prometheus'],
          ].map(([id, label]) => (
            <button key={id} onClick={() => setTab(id as any)}
              className={`px-4 py-2.5 text-xs font-medium whitespace-nowrap transition-colors border-b-2 ${tab === id ? 'border-blue-500 text-blue-400' : 'border-transparent text-slate-400 hover:text-white'}`}>
              {label}
            </button>
          ))}
        </div>

        {/* Not configured warning */}
        {!server.winrm_configured && (
          <div className="m-4 p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl text-sm text-amber-300">
            Bu sunucu için WinRM kimlik bilgisi tanımlanmamış. Sunucu listesinden "WinRM Ayarla" butonuna basın.
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">

          {/* Info Tab */}
          {tab === 'info' && server.winrm_configured && (
            <div className="space-y-4">
              {/* Performance */}
              {perfQ.data && (
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-slate-700/50 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <Cpu size={14} className="text-blue-400" />
                      <span className="text-xs text-slate-400 font-medium">CPU</span>
                    </div>
                    <div className="text-2xl font-bold text-white">{perfQ.data.cpu_pct ?? '—'}%</div>
                    <div className="mt-2 h-1.5 bg-slate-600 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full transition-all ${(perfQ.data.cpu_pct || 0) > 85 ? 'bg-red-500' : 'bg-blue-500'}`}
                        style={{ width: `${perfQ.data.cpu_pct || 0}%` }} />
                    </div>
                  </div>
                  <div className="bg-slate-700/50 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <MemoryStick size={14} className="text-purple-400" />
                      <span className="text-xs text-slate-400 font-medium">RAM</span>
                    </div>
                    <div className="text-2xl font-bold text-white">{perfQ.data.mem_used_pct ?? '—'}%</div>
                    <div className="mt-2 h-1.5 bg-slate-600 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full transition-all ${(perfQ.data.mem_used_pct || 0) > 85 ? 'bg-red-500' : 'bg-purple-500'}`}
                        style={{ width: `${perfQ.data.mem_used_pct || 0}%` }} />
                    </div>
                  </div>
                </div>
              )}

              {/* OS Info */}
              {infoQ.isPending && <div className="text-slate-400 text-sm">Bilgi alınıyor...</div>}
              {infoQ.data?.os && (
                <div className="bg-slate-700/40 rounded-xl p-4">
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">İşletim Sistemi</h4>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    {[
                      ['OS', infoQ.data.os.Caption],
                      ['Versiyon', infoQ.data.os.Version],
                      ['Build', infoQ.data.os.BuildNumber],
                      ['Mimari', infoQ.data.os.Architecture],
                      ['Hostname', infoQ.data.os.Hostname],
                      ['Domain', infoQ.data.os.Domain],
                      ['Son Boot', infoQ.data.os.LastBoot],
                    ].map(([k, v]) => v && (
                      <div key={k}>
                        <span className="text-slate-500">{k}: </span>
                        <span className="text-white">{v}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Disks */}
              {infoQ.data?.disks?.length > 0 && (
                <div className="bg-slate-700/40 rounded-xl p-4">
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Diskler</h4>
                  <div className="space-y-2">
                    {infoQ.data.disks.map((d: any) => {
                      const usedPct = d.TotalGB > 0 ? Math.round(d.UsedGB / d.TotalGB * 100) : 0
                      return (
                        <div key={d.Name}>
                          <div className="flex justify-between text-sm mb-1">
                            <span className="text-white font-mono">{d.Name}:\\</span>
                            <span className="text-slate-400">{d.UsedGB} / {d.TotalGB} GB ({usedPct}%)</span>
                          </div>
                          <div className="h-1.5 bg-slate-600 rounded-full overflow-hidden">
                            <div className={`h-full rounded-full ${usedPct > 85 ? 'bg-red-500' : usedPct > 70 ? 'bg-yellow-500' : 'bg-green-500'}`}
                              style={{ width: `${usedPct}%` }} />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Services Tab */}
          {tab === 'services' && server.winrm_configured && (
            <div className="space-y-3">
              <div className="relative">
                <Search size={14} className="absolute left-3 top-2.5 text-slate-500" />
                <input value={serviceSearch} onChange={e => setServiceSearch(e.target.value)}
                  placeholder="Servis ara..." className="w-full bg-slate-700 border border-slate-600 rounded-lg pl-8 pr-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              {servicesQ.isPending && <p className="text-slate-400 text-sm">Servisler yükleniyor...</p>}
              <div className="space-y-1 max-h-[500px] overflow-y-auto">
                {filteredServices.map(svc => {
                  const running = svc.Status?.toLowerCase() === 'running' || svc.Status === '4'
                  return (
                    <div key={svc.Name} className="flex items-center gap-3 bg-slate-700/40 rounded-lg px-3 py-2 hover:bg-slate-700/60">
                      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${running ? 'bg-green-400' : 'bg-slate-500'}`} />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-white truncate">{svc.DisplayName}</div>
                        <div className="text-xs text-slate-500 font-mono">{svc.Name}</div>
                      </div>
                      <span className="text-xs text-slate-500 mr-2 hidden sm:block">{svc.StartType}</span>
                      <div className="flex gap-1">
                        {!running && (
                          <button onClick={() => svcAction.mutate({ name: svc.Name, action: 'start' })}
                            className="p-1 rounded hover:bg-green-500/20 text-green-400" title="Başlat">
                            <Play size={12} />
                          </button>
                        )}
                        {running && (
                          <>
                            <button onClick={() => svcAction.mutate({ name: svc.Name, action: 'restart' })}
                              className="p-1 rounded hover:bg-blue-500/20 text-blue-400" title="Yeniden Başlat">
                              <RotateCcw size={12} />
                            </button>
                            <button onClick={() => svcAction.mutate({ name: svc.Name, action: 'stop' })}
                              className="p-1 rounded hover:bg-red-500/20 text-red-400" title="Durdur">
                              <Square size={12} />
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Event Log Tab */}
          {tab === 'events' && server.winrm_configured && (
            <div className="space-y-3">
              <div className="flex gap-2">
                {['System', 'Application', 'Security'].map(ch => (
                  <button key={ch} onClick={() => setLogChannel(ch)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${logChannel === ch ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-400 hover:text-white'}`}>
                    {ch}
                  </button>
                ))}
              </div>
              {eventsQ.isPending && <p className="text-slate-400 text-sm">Event log yükleniyor...</p>}
              <div className="space-y-1.5 max-h-[480px] overflow-y-auto">
                {(eventsQ.data || []).map((ev, i) => (
                  <div key={i} className="bg-slate-700/40 rounded-lg px-3 py-2 text-sm">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-xs font-semibold ${levelColor(ev.LevelDisplayName)}`}>
                        {ev.LevelDisplayName}
                      </span>
                      <span className="text-slate-500 text-xs">ID:{ev.Id}</span>
                      <span className="text-slate-500 text-xs ml-auto">{ev.TimeCreated?.slice(0, 16)}</span>
                    </div>
                    <div className="text-slate-300 text-xs">{ev.ProviderName}</div>
                    <div className="text-slate-400 text-xs mt-0.5 line-clamp-2">{ev.Message}</div>
                  </div>
                ))}
                {eventsQ.data?.length === 0 && <p className="text-slate-500 text-sm text-center py-6">Hata/uyarı kaydı yok</p>}
              </div>
            </div>
          )}

          {/* Updates Tab */}
          {tab === 'updates' && server.winrm_configured && (
            <div className="space-y-4">
              {updatesQ.isPending && <p className="text-slate-400 text-sm">Güncellemeler kontrol ediliyor...</p>}
              {updatesQ.data && (
                <>
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-white font-medium">{updatesQ.data.pending?.length || 0}</span>
                      <span className="text-slate-400 text-sm ml-2">bekleyen güncelleme</span>
                    </div>
                    {updatesQ.data.pending?.length > 0 && (
                      <button onClick={() => installAllUpdates.mutate()}
                        disabled={installAllUpdates.isPending}
                        className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors">
                        <Download size={13} />
                        {installAllUpdates.isPending ? 'Kuruluyor...' : 'Tümünü Kur'}
                      </button>
                    )}
                  </div>
                  {installAllUpdates.data && (
                    <div className={`p-3 rounded-lg text-sm ${installAllUpdates.data.status === 'success' ? 'bg-green-500/10 border border-green-500/30 text-green-300' : 'bg-red-500/10 border border-red-500/30 text-red-300'}`}>
                      {installAllUpdates.data.message}
                    </div>
                  )}
                  <div className="space-y-1.5 max-h-72 overflow-y-auto">
                    {(updatesQ.data.pending || []).map((u: UpdateItem, i: number) => (
                      <div key={i} className="bg-slate-700/40 rounded-lg px-3 py-2">
                        <div className="flex items-start gap-2">
                          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded mt-0.5 flex-shrink-0 ${
                            u.Severity === 'Critical' ? 'bg-red-500/20 text-red-400' :
                            u.Severity === 'Important' ? 'bg-orange-500/20 text-orange-400' :
                            'bg-slate-600 text-slate-400'
                          }`}>{u.Severity || 'Normal'}</span>
                          <div>
                            <div className="text-sm text-white">{u.Title}</div>
                            {u.KB && <div className="text-xs text-slate-500">KB{u.KB}</div>}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>

                  {updatesQ.data.installed?.length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Son Kurulan Güncellemeler</h4>
                      <div className="space-y-1 max-h-40 overflow-y-auto">
                        {updatesQ.data.installed.map((u: any, i: number) => (
                          <div key={i} className="flex items-center gap-2 text-xs text-slate-400 bg-slate-700/30 rounded px-2 py-1">
                            <CheckCircle size={11} className="text-green-400 flex-shrink-0" />
                            <span className="font-mono">{u.HotFixID}</span>
                            <span className="flex-1 truncate">{u.Description}</span>
                            <span className="text-slate-500 flex-shrink-0">{u.InstalledOn}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* Exporter Tab */}
          {tab === 'exporter' && server.winrm_configured && (
            <div className="space-y-4">
              {exporterQ.isPending && <p className="text-slate-400 text-sm">Durum kontrol ediliyor...</p>}
              {exporterQ.data && (
                <div className="bg-slate-700/40 rounded-xl p-4">
                  <div className="flex items-center gap-3 mb-4">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${exporterQ.data.running ? 'bg-green-500/20' : 'bg-slate-600/50'}`}>
                      <Activity size={18} className={exporterQ.data.running ? 'text-green-400' : 'text-slate-400'} />
                    </div>
                    <div>
                      <div className="text-white font-medium">Windows Exporter</div>
                      <div className={`text-sm ${exporterQ.data.running ? 'text-green-400' : 'text-slate-500'}`}>
                        {exporterQ.data.running ? 'Çalışıyor — Port 9182' :
                         exporterQ.data.installed ? 'Kurulu ama durdurulmuş' : 'Kurulu değil'}
                      </div>
                    </div>
                  </div>
                  <div className="text-xs text-slate-400 mb-4">
                    Windows Exporter, CPU, RAM, disk, network metriklerini Prometheus'a aktarır.
                    Port 9182 üzerinden scrape edilir.
                  </div>
                  {!exporterQ.data.installed && (
                    <button onClick={() => installExporter.mutate()}
                      disabled={installExporter.isPending}
                      className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors">
                      <Download size={14} />
                      {installExporter.isPending ? 'Kuruluyor...' : 'İndir & Kur'}
                    </button>
                  )}
                  {installExporter.data && (
                    <div className={`mt-3 p-3 rounded-lg text-sm ${installExporter.data.success ? 'bg-green-500/10 text-green-300' : 'bg-red-500/10 text-red-300'}`}>
                      {installExporter.data.success ? '✓ Kurulum başarılı' : `✗ ${installExporter.data.error}`}
                      {installExporter.data.steps && (
                        <div className="mt-2 space-y-0.5">
                          {installExporter.data.steps.map((s: any, i: number) => (
                            <div key={i} className="flex items-center gap-1.5 text-xs">
                              {s.ok ? <CheckCircle size={10} className="text-green-400" /> : <XCircle size={10} className="text-red-400" />}
                              <span>{s.step}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

        </div>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const WindowsServers: React.FC = () => {
  const [selected, setSelected] = useState<WindowsServer | null>(null)
  const [credServer, setCredServer] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const queryClient = useQueryClient()

  const { data: servers = [], isLoading, refetch } = useQuery<WindowsServer[]>({
    queryKey: ['windows-servers'],
    queryFn: async () => {
      const r = await fetch(`${WIN_API}/servers`)
      if (!r.ok) throw new Error('Yüklenemedi')
      return r.json()
    },
    refetchInterval: 60_000,
  })

  const testConn = useMutation({
    mutationFn: async (id: number) => {
      const r = await fetch(`${WIN_API}/servers/${id}/test-connection`, { method: 'POST' })
      return r.json()
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['windows-servers'] }),
  })

  const filtered = servers.filter(s =>
    !search ||
    s.name.toLowerCase().includes(search.toLowerCase()) ||
    s.ip_address?.includes(search)
  )

  const online = servers.filter(s => s.status === 'ONLINE').length
  const configured = servers.filter(s => s.winrm_configured).length

  return (
    <div className="space-y-6">
      {credServer && (
        <CredentialModal serverId={credServer} onClose={() => setCredServer(null)} />
      )}
      {selected && (
        <ServerDetail server={selected} onClose={() => setSelected(null)} />
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white">Windows Sunucular</h1>
          <p className="text-slate-400 text-sm mt-0.5">WinRM ile yönetilen Windows VM'ler ve fiziksel sunucular</p>
        </div>
        <button onClick={() => refetch()}
          className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded-lg transition-colors">
          <RefreshCw size={14} /> Yenile
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Toplam', value: servers.length, color: 'text-white' },
          { label: 'Aktif', value: online, color: 'text-green-400' },
          { label: 'WinRM Ayarlı', value: configured, color: 'text-blue-400' },
          { label: 'Ayarsız', value: servers.length - configured, color: 'text-amber-400' },
        ].map(s => (
          <div key={s.label} className="bg-slate-800 border border-slate-700 rounded-xl p-4">
            <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
            <div className="text-slate-400 text-xs mt-0.5">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Search */}
      <div className="relative max-w-xs">
        <Search size={14} className="absolute left-3 top-2.5 text-slate-500" />
        <input value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Sunucu ara..." className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-8 pr-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>

      {/* Server List */}
      {isLoading ? (
        <div className="flex items-center justify-center h-40 gap-3 text-slate-400">
          <div className="w-5 h-5 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
          Yükleniyor...
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-52 bg-slate-800 border border-slate-700 rounded-xl gap-3">
          <Shield size={40} className="text-slate-600" />
          <p className="text-slate-400 font-medium">Windows sunucu bulunamadı</p>
          <p className="text-slate-500 text-sm text-center max-w-xs">
            Hypervisor senkronizasyonundan Windows VM'ler otomatik eklenir,
            veya Sunucular sayfasından os_type=windows olan sunucu ekleyin.
          </p>
        </div>
      ) : (
        <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700 bg-slate-800/80">
                {['Sunucu', 'Durum', 'OS', 'CPU / RAM', 'WinRM', ''].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {filtered.map(srv => (
                <tr key={srv.id} className="hover:bg-slate-700/30 transition-colors cursor-pointer"
                  onClick={() => setSelected(srv)}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${srv.status === 'ONLINE' ? 'bg-blue-500/20' : 'bg-slate-700'}`}>
                        <span className="text-[9px] font-bold text-blue-400">WIN</span>
                      </div>
                      <div>
                        <div className="text-sm font-semibold text-white">{srv.name}</div>
                        <div className="text-xs text-slate-500 font-mono">{srv.ip_address || '—'}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">{statusBadge(srv.status)}</td>
                  <td className="px-4 py-3 text-sm text-slate-300">{srv.os_type || 'Windows'}</td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="text-xs text-slate-400">
                      {srv.cpu_cores > 0 && <div>{srv.cpu_cores} CPU</div>}
                      {srv.memory_gb > 0 && <div>{srv.memory_gb} GB RAM</div>}
                      {!srv.cpu_cores && !srv.memory_gb && <span className="text-slate-600">—</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    {srv.winrm_configured ? (
                      <span className="inline-flex items-center gap-1 text-xs text-blue-400">
                        <Wifi size={11} /> Port {srv.winrm_port}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs text-amber-500">
                        <WifiOff size={11} /> Ayarsız
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                    <div className="flex gap-1 justify-end">
                      {!srv.winrm_configured && (
                        <button onClick={() => setCredServer(srv.id)}
                          className="flex items-center gap-1 px-2.5 py-1 text-xs bg-blue-500/20 text-blue-400 hover:bg-blue-500/30 border border-blue-500/30 rounded-lg transition-colors">
                          <Settings size={11} /> WinRM Ayarla
                        </button>
                      )}
                      {srv.winrm_configured && (
                        <button
                          onClick={() => testConn.mutate(srv.id)}
                          disabled={testConn.isPending && testConn.variables === srv.id}
                          className="flex items-center gap-1 px-2.5 py-1 text-xs bg-slate-700 text-slate-300 hover:bg-slate-600 rounded-lg transition-colors">
                          <Wifi size={11} /> Test
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default WindowsServers
