import React, { useEffect, useState } from 'react'
import { useLocation, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Wifi, WifiOff, RefreshCw, Settings, Activity,
  Shield, Cpu, MemoryStick, Download, Play, Square, RotateCcw,
  Search, X, CheckCircle, XCircle, Globe, CheckCircle2, BrainCircuit } from 'lucide-react'
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
  disk_gb?: number
  hypervisor_id: number | null
  hypervisor_name: string | null
  winrm_configured: boolean
  winrm_source: 'server' | 'global' | null
  winrm_port: number | null
  confirmed_windows: boolean
  ai_ready: boolean
  windows_exporter_installed: boolean
  windows_exporter_running: boolean
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

// ── Event Log Panel (reused by modal and dedicated /windows/events view) ───────

const EventLogPanel: React.FC<{ server: WindowsServer }> = ({ server }) => {
  const [logChannel, setLogChannel] = useState('System')
  const [logLevel, setLogLevel] = useState(4) // 1=Kritik 2=Hata 3=Uyarı 4=Tümü (Information dahil)

  const eventsQ = useQuery({
    queryKey: ['win-events', server.id, logChannel, logLevel],
    queryFn: async () => {
      const r = await fetch(`${WIN_API}/servers/${server.id}/event-logs?log_name=${logChannel}&count=50&min_level=${logLevel}`)
      return r.json() as Promise<EventLogEntry[]>
    },
    enabled: server.winrm_configured,
  })

  if (!server.winrm_configured) {
    return (
      <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl text-sm text-amber-300">
        Bu sunucu için WinRM kimlik bilgisi tanımlanmamış. Sunucu listesinden "WinRM Ayarla" butonuna basın.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-2">
          {['System', 'Application', 'Security'].map(ch => (
            <button key={ch} onClick={() => setLogChannel(ch)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${logChannel === ch ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-400 hover:text-white'}`}>
              {ch}
            </button>
          ))}
        </div>
        <select
          value={logLevel}
          onChange={e => setLogLevel(Number(e.target.value))}
          className="bg-slate-700 border border-slate-600 rounded-lg text-xs text-slate-200 px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
          title="Önem seviyesi filtresi"
        >
          <option value={4}>Tümü (Bilgi dahil)</option>
          <option value={3}>Uyarı ve üzeri</option>
          <option value={2}>Hata ve üzeri</option>
          <option value={1}>Sadece Kritik</option>
        </select>
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
        {!eventsQ.isPending && eventsQ.data?.length === 0 && (
          <p className="text-slate-500 text-sm text-center py-6">
            Bu kanalda/seviyede kayıt yok. Seçili filtre: <span className="text-slate-400">{logChannel}</span>,{' '}
            <span className="text-slate-400">{logLevel === 4 ? 'Tümü' : logLevel === 3 ? 'Uyarı+' : logLevel === 2 ? 'Hata+' : 'Kritik'}</span>.
            Farklı bir kanal veya "Tümü" seviyesini deneyin.
          </p>
        )}
      </div>
    </div>
  )
}

// ── Updates Panel (reused by modal and dedicated /windows/updates view) ────────

const UpdatesPanel: React.FC<{ server: WindowsServer }> = ({ server }) => {
  const queryClient = useQueryClient()

  const updatesQ = useQuery({
    queryKey: ['win-updates', server.id],
    queryFn: async () => {
      const r = await fetch(`${WIN_API}/servers/${server.id}/updates`)
      return r.json()
    },
    enabled: server.winrm_configured,
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

  if (!server.winrm_configured) {
    return (
      <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl text-sm text-amber-300">
        Bu sunucu için WinRM kimlik bilgisi tanımlanmamış. Sunucu listesinden "WinRM Ayarla" butonuna basın.
      </div>
    )
  }

  return (
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
  )
}

// ── Credential Modal ──────────────────────────────────────────────────────────

const CredentialModal: React.FC<{ server: WindowsServer; onClose: () => void }> = ({ server, onClose }) => {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    username: '',
    password: '',
    port: 5985,
    use_https: false,
    ip_address: server.ip_address || '',
  })
  const [result, setResult] = useState<any>(null)

  const save = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${WIN_API}/servers/${server.id}/save-credentials`, {
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

  const hasIp = !!(server.ip_address || form.ip_address.trim())

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-800 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h3 className="text-white font-semibold">WinRM Kimlik Bilgileri</h3>
            <p className="text-slate-500 text-xs mt-0.5">{server.name}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={18} /></button>
        </div>
        <div className="space-y-3">
          {/* IP Address — required if missing */}
          <div>
            <label className="text-xs mb-1 flex items-center gap-1">
              <span className={!hasIp ? 'text-amber-400' : 'text-slate-400'}>IP Adresi</span>
              {!server.ip_address && <span className="text-amber-500 text-[10px]">● Gerekli — hypervisor'dan alınamadı</span>}
            </label>
            <input
              value={form.ip_address}
              onChange={e => setForm(f => ({ ...f, ip_address: e.target.value }))}
              className={`w-full bg-slate-700 border rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono ${!hasIp ? 'border-amber-500/60' : 'border-slate-600'}`}
              placeholder="192.168.1.x" />
          </div>
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
              <label className="text-xs text-slate-400 mb-1 block">WinRM Port</label>
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
              {result.connection_test?.connected
                ? '✓ Bağlantı başarılı'
                : `✗ ${result.connection_test?.message || 'Bağlantı başarısız'}`}
            </div>
          )}
          <button
            onClick={() => save.mutate()}
            disabled={save.isPending || !form.username || !form.password || !form.ip_address.trim()}
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg font-medium text-sm transition-colors"
          >
            {save.isPending ? 'Kaydediliyor & Test Ediliyor...' : 'Kaydet & Test Et'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Server Detail Panel ───────────────────────────────────────────────────────

const ServerDetail: React.FC<{
  server: WindowsServer
  onClose: () => void
  initialTab?: 'info' | 'services' | 'events' | 'updates' | 'exporter'
}> = ({ server, onClose, initialTab }) => {
  const [tab, setTab] = useState<'info' | 'services' | 'events' | 'updates' | 'exporter'>(initialTab || 'info')
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
          {tab === 'events' && server.winrm_configured && <EventLogPanel server={server} />}

          {/* Updates Tab */}
          {tab === 'updates' && server.winrm_configured && <UpdatesPanel server={server} />}

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

// ── WinRM AI Ready Güncelle Butonu ──────────────────────────────────────────────
const WinRmAiReadyButton: React.FC<{ onDone: () => void }> = ({ onDone }) => {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<{ ai_ready_count: number; not_ready_count: number; tested: number } | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const handleClick = async () => {
    setConfirmOpen(false)
    setLoading(true); setResult(null)
    try {
      const r = await fetch(`${WIN_API}/update-ai-ready`, { method: 'POST' })
      if (r.ok) {
        const d = await r.json()
        setResult(d)
        onDone()
        setTimeout(() => setResult(null), 8000)
      }
    } finally { setLoading(false) }
  }

  return (
    <>
      {confirmOpen && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={() => setConfirmOpen(false)}>
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 max-w-sm w-full" onClick={e => e.stopPropagation()}>
            <p className="text-sm text-slate-200">
              Tüm Windows sunucularında WinRM bağlantısı test edilecek. Sunucuya özel kimlik bilgisi yoksa global WinRM kimlik bilgisi denenecek. Bağlanabilenler → AI Ready = ✅, bağlanamayanlar → ❌. Devam?
            </p>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setConfirmOpen(false)} className="px-3 py-1.5 text-sm text-slate-400 hover:text-white">Vazgeç</button>
              <button onClick={handleClick} className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg">Devam</button>
            </div>
          </div>
        </div>
      )}
      <button
        onClick={() => setConfirmOpen(true)}
        disabled={loading}
        className="flex items-center gap-2 px-4 py-2 bg-blue-600/90 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
        title="WinRM Credentials ile bağlanıp AI Ready durumunu güncelle"
      >
        {loading ? (
          <>
            <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin flex-shrink-0" />
            Test ediliyor...
          </>
        ) : result ? (
          <>
            <CheckCircle2 size={14} className="text-green-300" />
            {result.ai_ready_count} AI Ready · {result.not_ready_count} bağlanamadı
          </>
        ) : (
          <>
            <BrainCircuit size={14} /> AI Ready Güncelle
          </>
        )}
      </button>
    </>
  )
}

// ── Dedicated Event Log / Windows Update view ───────────────────────────────────
// "Event Log" ve "Windows Update" ana menüleri artık genel sunucu listesini
// (istatistik kartları, arama, tablo) hiç göstermez — doğrudan bir sunucu
// seçici + ilgili panel açılır. Böylece menüye tıklanınca "alakasız" bir
// sunucu yönetim ekranı görünmez.
const FocusedServerView: React.FC<{
  tab: 'events' | 'updates'
  servers: WindowsServer[]
  isLoading: boolean
}> = ({ tab, servers, isLoading }) => {
  const configured = servers.filter(s => s.winrm_configured)
  const [selectedId, setSelectedId] = useState<number | null>(null)

  useEffect(() => {
    if (configured.length === 0) return
    if (selectedId === null || !configured.some(s => s.id === selectedId)) {
      setSelectedId(configured[0].id)
    }
  }, [configured, selectedId])

  const selected = configured.find(s => s.id === selectedId) || null

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-40 gap-3 text-slate-400">
        <div className="w-5 h-5 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
        Yükleniyor...
      </div>
    )
  }

  if (configured.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-52 bg-slate-800 border border-slate-700 rounded-xl gap-3">
        <Shield size={40} className="text-slate-600" />
        <p className="text-slate-400 font-medium">WinRM ayarlı Windows sunucu bulunamadı</p>
        <p className="text-slate-500 text-sm text-center max-w-sm">
          {tab === 'events' ? 'Event Log' : 'Windows Update'} görüntülemek için önce{' '}
          <Link to="/windows" className="text-blue-400 hover:underline">Windows Sunucular</Link> sayfasından
          bir sunucuya WinRM kimlik bilgisi tanımlayın.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 bg-slate-800 border border-slate-700 rounded-xl p-3">
        <span className="text-xs text-slate-400 font-medium flex-shrink-0">Sunucu:</span>
        <select
          value={selectedId ?? ''}
          onChange={e => setSelectedId(Number(e.target.value))}
          className="bg-slate-700 border border-slate-600 rounded-lg text-sm text-white px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {configured.map(s => (
            <option key={s.id} value={s.id}>{s.name} ({s.ip_address || s.hostname || '—'})</option>
          ))}
        </select>
        {selected && statusBadge(selected.status)}
        {selected && !selected.ai_ready && (
          <span className="inline-flex items-center gap-1 text-[10px] text-amber-400">
            <XCircle size={9} /> AI Ready değil — bağlantı sorunlu olabilir
          </span>
        )}
        <Link to="/windows" className="ml-auto text-xs text-blue-400 hover:underline flex-shrink-0">
          Tüm Sunucular →
        </Link>
      </div>
      {selected && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
          {tab === 'events' ? <EventLogPanel server={selected} /> : <UpdatesPanel server={selected} />}
        </div>
      )}
    </div>
  )
}

// ── Windows Exporter Toplu Kurulum Butonu ───────────────────────────────────────
const WindowsExporterInstallAllButton: React.FC<{ onDone: () => void }> = ({ onDone }) => {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<{ installed_count: number; failed_count: number; tested: number } | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const handleClick = async () => {
    setConfirmOpen(false)
    setLoading(true); setResult(null)
    try {
      const r = await fetch(`${WIN_API}/exporter/install-all`, { method: 'POST' })
      if (r.ok) {
        const d = await r.json()
        setResult(d)
        onDone()
        setTimeout(() => setResult(null), 8000)
      }
    } finally { setLoading(false) }
  }

  return (
    <>
      {confirmOpen && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={() => setConfirmOpen(false)}>
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 max-w-sm w-full" onClick={e => e.stopPropagation()}>
            <p className="text-sm text-slate-200">
              AI Ready olan ve henüz windows_exporter kurulu olmayan tüm sunuculara WinRM üzerinden
              windows_exporter (Prometheus, port 9182) kurulacak. Sunucu başına ~30-60 sn sürebilir. Devam?
            </p>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setConfirmOpen(false)} className="px-3 py-1.5 text-sm text-slate-400 hover:text-white">Vazgeç</button>
              <button onClick={handleClick} className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg">Devam</button>
            </div>
          </div>
        </div>
      )}
      <button
        onClick={() => setConfirmOpen(true)}
        disabled={loading}
        className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
        title="Tüm AI Ready sunuculara windows_exporter kur (Prometheus canlı metrikler için)"
      >
        {loading ? (
          <>
            <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin flex-shrink-0" />
            Kuruluyor...
          </>
        ) : result ? (
          <>
            <CheckCircle2 size={14} className="text-green-300" />
            {result.installed_count} kuruldu · {result.failed_count} başarısız
          </>
        ) : (
          <>
            <Download size={14} /> windows_exporter Kur
          </>
        )}
      </button>
    </>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const WindowsServers: React.FC = () => {
  const location = useLocation()
  const routeTab: 'events' | 'updates' | null =
    location.pathname === '/windows/events' ? 'events' :
    location.pathname === '/windows/updates' ? 'updates' : null

  const [selected, setSelected] = useState<WindowsServer | null>(null)
  const [credServer, setCredServer] = useState<WindowsServer | null>(null)
  const [search, setSearch] = useState('')
  const [showUnclassified, setShowUnclassified] = useState(false)
  const queryClient = useQueryClient()

  const { data: servers = [], isLoading, refetch } = useQuery<WindowsServer[]>({
    queryKey: ['windows-servers', showUnclassified],
    queryFn: async () => {
      const r = await fetch(`${WIN_API}/servers?include_unclassified=${showUnclassified}`)
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

  const confirmedWindows = servers.filter(s => s.confirmed_windows)
  const unclassified = servers.filter(s => !s.confirmed_windows)
  const online = servers.filter(s => s.status === 'ONLINE').length
  const configured = servers.filter(s => s.winrm_configured).length
  const aiReadyCount = servers.filter(s => s.ai_ready).length
  const exporterRunningCount = servers.filter(s => s.windows_exporter_running).length

  return (
    <div className="space-y-6">
      {credServer && (
        <CredentialModal server={credServer} onClose={() => setCredServer(null)} />
      )}
      {selected && (
        <ServerDetail server={selected} onClose={() => setSelected(null)} />
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white">
            {routeTab === 'events' ? 'Windows Event Log' : routeTab === 'updates' ? 'Windows Update' : 'Windows Sunucular'}
          </h1>
          <p className="text-slate-400 text-sm mt-0.5">
            {routeTab === 'events'
              ? 'Bir sunucu seçerek WinRM üzerinden canlı Event Log kayıtlarını görüntüleyin'
              : routeTab === 'updates'
              ? 'Bir sunucu seçerek bekleyen Windows güncellemelerini görüntüleyin ve kurun'
              : "WinRM ile yönetilen Windows VM'ler ve fiziksel sunucular"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Toggle unclassified VMs — sadece genel liste görünümünde anlamlı */}
          {!routeTab && (
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <div
                onClick={() => setShowUnclassified(v => !v)}
                className={`relative w-9 h-5 rounded-full transition-colors ${showUnclassified ? 'bg-blue-600' : 'bg-slate-600'}`}
              >
                <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${showUnclassified ? 'translate-x-4' : ''}`} />
              </div>
              <span className="text-xs text-slate-400">OS Belirsiz VM'ler</span>
            </label>
          )}
          {!routeTab && <WinRmAiReadyButton onDone={refetch} />}
          {!routeTab && <WindowsExporterInstallAllButton onDone={refetch} />}
          <button onClick={() => refetch()}
            className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded-lg transition-colors">
            <RefreshCw size={14} /> Yenile
          </button>
        </div>
      </div>

      {routeTab ? (
        <FocusedServerView tab={routeTab} servers={servers} isLoading={isLoading} />
      ) : (
      <>
      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-6 gap-3">
        {[
          { label: 'Windows Tespit', value: confirmedWindows.length, color: 'text-blue-400' },
          { label: 'OS Belirsiz', value: unclassified.length, color: 'text-amber-400' },
          { label: 'Aktif', value: online, color: 'text-green-400' },
          { label: 'WinRM Ayarlı', value: configured, color: 'text-cyan-400' },
          { label: 'AI Ready', value: aiReadyCount, color: 'text-emerald-400' },
          { label: 'Exporter Çalışıyor', value: exporterRunningCount, color: 'text-purple-400' },
        ].map(s => (
          <div key={s.label} className="bg-slate-800 border border-slate-700 rounded-xl p-4">
            <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
            <div className="text-slate-400 text-xs mt-0.5">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Unclassified notice */}
      {showUnclassified && unclassified.length > 0 && (
        <div className="flex items-start gap-3 p-4 bg-amber-500/8 border border-amber-500/25 rounded-xl text-sm">
          <Shield size={16} className="text-amber-400 mt-0.5 flex-shrink-0" />
          <div>
            <span className="text-amber-300 font-medium">{unclassified.length} VM</span>
            <span className="text-amber-400/80"> hypervisor'dan senkronize edildi fakat işletim sistemi belirlenmedi. Bunlar Windows olabilir — WinRM bilgilerini girerek bağlantı kurun.</span>
          </div>
        </div>
      )}

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
          <p className="text-slate-500 text-sm text-center max-w-sm">
            Henüz tanımlı Windows sunucu yok.<br/>
            Hypervisor senkronizasyonundan Windows VM'ler otomatik eklenir.<br/>
            <span className="text-slate-600">
              "OS Belirsiz VM'ler" toggle'ı açarak sınıflandırılmamış VM'leri de görebilirsiniz.
            </span>
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
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                        srv.confirmed_windows
                          ? srv.status === 'ONLINE' ? 'bg-blue-500/20' : 'bg-slate-700'
                          : 'bg-amber-500/10'
                      }`}>
                        <span className={`text-[9px] font-bold ${srv.confirmed_windows ? 'text-blue-400' : 'text-amber-500'}`}>
                          {srv.confirmed_windows ? 'WIN' : '?'}
                        </span>
                      </div>
                      <div>
                        <div className="text-sm font-semibold text-white">{srv.name}</div>
                        <div className="text-xs text-slate-500 font-mono">
                          {srv.ip_address || srv.hostname || '—'}
                          {srv.hypervisor_name && <span className="ml-2 text-slate-600">· {srv.hypervisor_name}</span>}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">{statusBadge(srv.status)}</td>
                  <td className="px-4 py-3 text-sm">
                    {srv.confirmed_windows
                      ? <span className="text-slate-300">{srv.os_type}</span>
                      : <span className="text-amber-500/70 text-xs italic">Belirsiz ({srv.os_type || 'boş'})</span>
                    }
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="text-xs text-slate-400">
                      {srv.cpu_cores > 0 && <div>{srv.cpu_cores} CPU</div>}
                      {srv.memory_gb > 0 && <div>{srv.memory_gb} GB RAM</div>}
                      {!srv.cpu_cores && !srv.memory_gb && <span className="text-slate-600">—</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    {srv.winrm_configured ? (
                      <div className="flex flex-col gap-0.5">
                        <span className="inline-flex items-center gap-1 text-xs text-blue-400">
                          <Wifi size={11} /> Port {srv.winrm_port}
                        </span>
                        {srv.winrm_source === 'global' && (
                          <span className="inline-flex items-center gap-1 text-[10px] text-slate-500">
                            <Globe size={9} /> global
                          </span>
                        )}
                        {srv.ai_ready ? (
                          <span className="inline-flex items-center gap-1 text-[10px] text-emerald-400">
                            <CheckCircle2 size={9} /> AI Ready
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[10px] text-slate-600">
                            <XCircle size={9} /> AI Ready değil
                          </span>
                        )}
                        {srv.windows_exporter_running ? (
                          <span className="inline-flex items-center gap-1 text-[10px] text-purple-400">
                            <Activity size={9} /> Exporter çalışıyor
                          </span>
                        ) : srv.windows_exporter_installed ? (
                          <span className="inline-flex items-center gap-1 text-[10px] text-amber-500">
                            <Activity size={9} /> Exporter durdu
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[10px] text-slate-600">
                            <Activity size={9} /> Exporter yok
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs text-amber-500">
                        <WifiOff size={11} /> Ayarsız
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                    <div className="flex gap-1 justify-end">
                      {!srv.winrm_configured && (
                        <button onClick={() => setCredServer(srv)}
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
      </>
      )}
    </div>
  )
}

export default WindowsServers
