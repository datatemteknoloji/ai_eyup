import React, { useEffect, useState } from 'react'
import { useLocation, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Wifi, WifiOff, RefreshCw, Settings, Activity,
  Shield, Cpu, MemoryStick, Download, Play, Square, RotateCcw,
  Search, X, CheckCircle, XCircle, Globe, CheckCircle2, BrainCircuit } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import BulkJobOverlay, { persistBulkJobId, restoreActiveBulkJobId, beginBulkJobModal } from '../components/BulkJobOverlay'
import { OsIcon } from '../components/OsIcon'
import { fullOsLabel, shortenOsLabel, serverTypeLabel } from '../lib/osLabel'
import { useT } from '../i18n/LocaleProvider'

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
  server_type?: string
  os_version?: string
  os_release_id?: string
  os_version_id?: string
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

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const t = useT()
  if (status === 'ONLINE') return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-500/15 text-green-400 border border-green-500/30">
      <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" /> {t('status_online')}
    </span>
  )
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-500/15 text-slate-400 border border-slate-600/40">
      <span className="w-1.5 h-1.5 bg-slate-500 rounded-full" /> {t('status_offline')}
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
  const t = useT()
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
        {t('win_winrm_missing')}
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
          title={t('win_level_filter')}
        >
          <option value={4}>{t('win_level_all')}</option>
          <option value={3}>{t('win_level_warn')}</option>
          <option value={2}>{t('win_level_error')}</option>
          <option value={1}>{t('win_level_crit')}</option>
        </select>
      </div>
      {eventsQ.isPending && <p className="text-slate-400 text-sm">{t('win_events_loading')}</p>}
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
            {t('win_no_events', {
              channel: logChannel,
              level: logLevel === 4 ? t('win_level_all_short') : logLevel === 3 ? t('win_level_warn_short') : logLevel === 2 ? t('win_level_error_short') : t('win_level_crit_short'),
            })}
          </p>
        )}
      </div>
    </div>
  )
}

// ── Updates Panel (reused by modal and dedicated /windows/updates view) ────────

const UpdatesPanel: React.FC<{ server: WindowsServer }> = ({ server }) => {
  const t = useT()
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
        {t('win_winrm_missing')}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {updatesQ.isPending && <p className="text-slate-400 text-sm">{t('win_updates_checking')}</p>}
      {updatesQ.data && (
        <>
          <div className="flex items-center justify-between">
            <div>
              <span className="text-white font-medium">{updatesQ.data.pending?.length || 0}</span>
              <span className="text-slate-400 text-sm ml-2">{t('win_pending_updates')}</span>
            </div>
            {updatesQ.data.pending?.length > 0 && (
              <button onClick={() => installAllUpdates.mutate()}
                disabled={installAllUpdates.isPending}
                className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors">
                <Download size={13} />
                {installAllUpdates.isPending ? t('win_installing') : t('win_install_all')}
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
              <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">{t('win_recent_updates')}</h4>
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
  const t = useT()
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
            <h3 className="text-white font-semibold">{t('win_creds_title')}</h3>
            <p className="text-slate-500 text-xs mt-0.5">{server.name}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={18} /></button>
        </div>
        <div className="space-y-3">
          {/* IP Address — required if missing */}
          <div>
            <label className="text-xs mb-1 flex items-center gap-1">
              <span className={!hasIp ? 'text-amber-400' : 'text-slate-400'}>{t('label_ip')}</span>
              {!server.ip_address && <span className="text-amber-500 text-[10px]">{t('win_ip_required')}</span>}
            </label>
            <input
              value={form.ip_address}
              onChange={e => setForm(f => ({ ...f, ip_address: e.target.value }))}
              className={`w-full bg-slate-700 border rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono ${!hasIp ? 'border-amber-500/60' : 'border-slate-600'}`}
              placeholder="192.168.1.x" />
          </div>
          <div>
            <label className="text-xs text-slate-400 mb-1 block">{t('win_username')}</label>
            <input value={form.username} onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
              className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Administrator" />
          </div>
          <div>
            <label className="text-xs text-slate-400 mb-1 block">{t('win_password')}</label>
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
                ? <span className="inline-flex items-center gap-1.5"><CheckCircle2 size={14} strokeWidth={2} /> {t('win_conn_ok')}</span>
                : <span className="inline-flex items-center gap-1.5"><XCircle size={14} strokeWidth={2} /> {result.connection_test?.message || t('win_conn_fail')}</span>}
            </div>
          )}
          <button
            onClick={() => save.mutate()}
            disabled={save.isPending || !form.username || !form.password || !form.ip_address.trim()}
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg font-medium text-sm transition-colors"
          >
            {save.isPending ? t('win_saving_test') : t('win_save_test')}
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
  const t = useT()
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
          <StatusBadge status={server.status} />
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none ml-2">&times;</button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-slate-700 bg-slate-800/60 overflow-x-auto">
          {[
            ['info', t('win_tab_system')],
            ['services', t('win_tab_services')],
            ['events', 'Event Log'],
            ['updates', t('win_tab_updates')],
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
            {t('win_winrm_missing')}
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
                      <MemoryStick size={14} className="text-sky-400" />
                      <span className="text-xs text-slate-400 font-medium">{t('memory')}</span>
                    </div>
                    <div className="text-2xl font-bold text-white">{perfQ.data.mem_used_pct ?? '—'}%</div>
                    <div className="mt-2 h-1.5 bg-slate-600 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full transition-all ${(perfQ.data.mem_used_pct || 0) > 85 ? 'bg-red-500' : 'bg-sky-500'}`}
                        style={{ width: `${perfQ.data.mem_used_pct || 0}%` }} />
                    </div>
                  </div>
                </div>
              )}

              {/* OS Info */}
              {infoQ.isPending && <div className="text-slate-400 text-sm">{t('win_info_loading')}</div>}
              {infoQ.data?.os && (
                <div className="bg-slate-700/40 rounded-xl p-4">
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">{t('win_os')}</h4>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    {[
                      [t('win_os'), infoQ.data.os.Caption],
                      [t('win_version'), infoQ.data.os.Version],
                      ['Build', infoQ.data.os.BuildNumber],
                      [t('win_arch'), infoQ.data.os.Architecture],
                      ['Hostname', infoQ.data.os.Hostname],
                      ['Domain', infoQ.data.os.Domain],
                      [t('win_last_boot'), infoQ.data.os.LastBoot],
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
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">{t('win_disks')}</h4>
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
                  placeholder={t('win_search_service')} className="w-full bg-slate-700 border border-slate-600 rounded-lg pl-8 pr-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              {servicesQ.isPending && <p className="text-slate-400 text-sm">{t('win_services_loading')}</p>}
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
                            className="p-1 rounded hover:bg-green-500/20 text-green-400" title={t('win_start')}>
                            <Play size={12} />
                          </button>
                        )}
                        {running && (
                          <>
                            <button onClick={() => svcAction.mutate({ name: svc.Name, action: 'restart' })}
                              className="p-1 rounded hover:bg-blue-500/20 text-blue-400" title={t('win_restart')}>
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
              {exporterQ.isPending && <p className="text-slate-400 text-sm">{t('win_checking_status')}</p>}
              {exporterQ.data && (
                <div className="bg-slate-700/40 rounded-xl p-4">
                  <div className="flex items-center gap-3 mb-4">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${exporterQ.data.running ? 'bg-green-500/20' : 'bg-slate-600/50'}`}>
                      <Activity size={18} className={exporterQ.data.running ? 'text-green-400' : 'text-slate-400'} />
                    </div>
                    <div>
                      <div className="text-white font-medium">Windows Exporter</div>
                      <div className={`text-sm ${exporterQ.data.running ? 'text-green-400' : 'text-slate-500'}`}>
                        {exporterQ.data.running ? t('win_exporter_port') :
                         exporterQ.data.installed ? t('win_exporter_installed_stopped') : t('win_exporter_not_installed')}
                      </div>
                    </div>
                  </div>
                  <div className="text-xs text-slate-400 mb-4">
                    {t('win_exporter_hint')}
                  </div>
                  {!exporterQ.data.installed && (
                    <button onClick={() => installExporter.mutate()}
                      disabled={installExporter.isPending}
                      className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors">
                      <Download size={14} />
                      {installExporter.isPending ? t('win_installing') : t('win_install_download')}
                    </button>
                  )}
                  {installExporter.data && (
                    <div className={`mt-3 p-3 rounded-lg text-sm ${installExporter.data.success ? 'bg-green-500/10 text-green-300' : 'bg-red-500/10 text-red-300'}`}>
                      {installExporter.data.success
                        ? <span className="inline-flex items-center gap-1.5"><CheckCircle2 size={14} strokeWidth={2} /> {t('win_install_ok')}</span>
                        : <span className="inline-flex items-center gap-1.5"><XCircle size={14} strokeWidth={2} /> {installExporter.data.error}</span>}
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
  const t = useT()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [bulkJobId, setBulkJobId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    restoreActiveBulkJobId().then(id => {
      if (!cancelled && id) setBulkJobId(id)
    })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    persistBulkJobId(bulkJobId)
  }, [bulkJobId])

  const handleClick = async () => {
    setConfirmOpen(false)
    setLoading(true); setResult(null)
    try {
      const r = await fetch(`${WIN_API}/update-ai-ready`, { method: 'POST' })
      if (r.ok) {
        const d = await r.json()
        if (d.job_id) {
          beginBulkJobModal(d.job_id)
          setBulkJobId(d.job_id)
        } else {
          setResult(d.message || `${d.ai_ready_count ?? 0} AI Ready`)
          onDone()
          setTimeout(() => setResult(null), 8000)
        }
      }
    } finally { setLoading(false) }
  }

  return (
    <>
      {bulkJobId && (
        <BulkJobOverlay
          jobId={bulkJobId}
          onDone={() => onDone()}
          onDismiss={() => {
            setBulkJobId(null)
            onDone()
          }}
        />
      )}
      {confirmOpen && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={() => setConfirmOpen(false)}>
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 max-w-sm w-full" onClick={e => e.stopPropagation()}>
            <p className="text-sm text-slate-200">
              {t('win_ai_ready_confirm')}
            </p>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setConfirmOpen(false)} className="px-3 py-1.5 text-sm text-slate-400 hover:text-white">{t('cancel')}</button>
              <button onClick={handleClick} className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg">{t('continue_action')}</button>
            </div>
          </div>
        </div>
      )}
      <button
        onClick={() => setConfirmOpen(true)}
        disabled={loading || !!bulkJobId}
        className="flex items-center gap-2 px-4 py-2 bg-blue-600/90 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
        title={t('win_ai_ready_title')}
      >
        {loading ? (
          <>
            <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin flex-shrink-0" />
            {t('starting')}
          </>
        ) : result ? (
          <>
            <CheckCircle2 size={14} className="text-green-300" />
            {result}
          </>
        ) : (
          <>
            <BrainCircuit size={14} /> {t('ai_ready_update')}
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
  const t = useT()
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
        {t('loading')}
      </div>
    )
  }

  if (configured.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-52 bg-slate-800 border border-slate-700 rounded-xl gap-3">
        <Shield size={40} className="text-slate-600" />
        <p className="text-slate-400 font-medium">{t('win_no_winrm_servers')}</p>
        <p className="text-slate-500 text-sm text-center max-w-sm">
          {t('win_focused_hint', { what: tab === 'events' ? 'Event Log' : 'Windows Update' })}{' '}
          <Link to="/windows" className="text-blue-400 hover:underline">{t('win_title')}</Link>
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 bg-slate-800 border border-slate-700 rounded-xl p-3">
        <span className="text-xs text-slate-400 font-medium flex-shrink-0">{t('win_pick_server')}</span>
        <select
          value={selectedId ?? ''}
          onChange={e => setSelectedId(Number(e.target.value))}
          className="bg-slate-700 border border-slate-600 rounded-lg text-sm text-white px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {configured.map(s => (
            <option key={s.id} value={s.id}>{s.name} ({s.ip_address || s.hostname || '—'})</option>
          ))}
        </select>
        {selected && <StatusBadge status={selected.status} />}
        {selected && !selected.ai_ready && (
          <span className="inline-flex items-center gap-1 text-[10px] text-amber-400">
            <XCircle size={9} /> {t('win_ai_ready_conn_issue')}
          </span>
        )}
        <Link to="/windows" className="ml-auto text-xs text-blue-400 hover:underline flex-shrink-0">
          {t('win_all_servers')}
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
const WindowsExporterInstallAllButton: React.FC<{ onDone: () => void; onJobStart?: (jobId: string) => void }> = ({ onDone, onJobStart }) => {
  const t = useT()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const handleClick = async () => {
    setConfirmOpen(false)
    setLoading(true); setResult(null)
    try {
      const r = await fetch(`${WIN_API}/exporter/install-all`, { method: 'POST' })
      if (r.ok) {
        const d = await r.json()
        if (d.job_id && onJobStart) {
          onJobStart(d.job_id)
        } else {
          setResult(d.message || `${d.installed_count ?? 0} kuruldu`)
          onDone()
          setTimeout(() => setResult(null), 8000)
        }
      }
    } finally { setLoading(false) }
  }

  return (
    <>
      {confirmOpen && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={() => setConfirmOpen(false)}>
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 max-w-sm w-full" onClick={e => e.stopPropagation()}>
            <p className="text-sm text-slate-200">
              {t('win_exporter_all_confirm')}
            </p>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setConfirmOpen(false)} className="px-3 py-1.5 text-sm text-slate-400 hover:text-white">{t('cancel')}</button>
              <button onClick={handleClick} className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg">{t('continue_action')}</button>
            </div>
          </div>
        </div>
      )}
      <button
        onClick={() => setConfirmOpen(true)}
        disabled={loading}
        className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
        title={t('win_exporter_all_title')}
      >
        {loading ? (
          <>
            <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin flex-shrink-0" />
            {t('starting')}
          </>
        ) : result ? (
          <>
            <CheckCircle2 size={14} className="text-green-300" />
            <span className="truncate text-xs max-w-[180px]">{result}</span>
          </>
        ) : (
          <>
            <Download size={14} /> {t('win_exporter_install')}
          </>
        )}
      </button>
    </>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const WindowsServers: React.FC = () => {
  const t = useT()
  const location = useLocation()
  const routeTab: 'events' | 'updates' | null =
    location.pathname === '/windows/events' ? 'events' :
    location.pathname === '/windows/updates' ? 'updates' : null

  const [selected, setSelected] = useState<WindowsServer | null>(null)
  const [credServer, setCredServer] = useState<WindowsServer | null>(null)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 50
  const [showUnclassified, setShowUnclassified] = useState(false)
  const [pageBulkJobId, setPageBulkJobId] = useState<string | null>(null)
  const queryClient = useQueryClient()

  useEffect(() => { setPage(1) }, [search, showUnclassified])

  useEffect(() => {
    let cancelled = false
    restoreActiveBulkJobId().then(id => {
      if (!cancelled && id) setPageBulkJobId(id)
    })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    persistBulkJobId(pageBulkJobId)
  }, [pageBulkJobId])

  const { data: serversPage, isLoading, refetch } = useQuery({
    queryKey: ['windows-servers', showUnclassified, page, pageSize, search],
    queryFn: async () => {
      const sp = new URLSearchParams({
        include_unclassified: String(showUnclassified),
        page: String(page),
        page_size: String(pageSize),
      })
      if (search.trim()) sp.set('q', search.trim())
      const r = await fetch(`${WIN_API}/servers?${sp}`)
      if (!r.ok) throw new Error('Yüklenemedi')
      const data = await r.json()
      if (Array.isArray(data)) {
        return { items: data as WindowsServer[], total: data.length, page: 1, page_size: data.length }
      }
      return data as { items: WindowsServer[]; total: number; page: number; page_size: number }
    },
    refetchInterval: 60_000,
  })

  const { data: winSummary } = useQuery({
    queryKey: ['windows-servers-summary', showUnclassified],
    queryFn: async () => {
      const r = await fetch(`${WIN_API}/servers/summary?include_unclassified=${showUnclassified}`)
      if (!r.ok) return null
      return r.json() as Promise<{
        total: number; online: number; winrm_configured: number; ai_ready: number
        windows_exporter_running: number; confirmed_windows: number
      }>
    },
    refetchInterval: 60_000,
  })

  const servers = serversPage?.items ?? []
  const totalServers = serversPage?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(totalServers / pageSize))

  const testConn = useMutation({
    mutationFn: async (id: number) => {
      const r = await fetch(`${WIN_API}/servers/${id}/test-connection`, { method: 'POST' })
      return r.json()
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['windows-servers'] }),
  })

  const filtered = servers
  const confirmedWindows = servers.filter(s => s.confirmed_windows)
  const unclassified = servers.filter(s => !s.confirmed_windows)
  const online = winSummary?.online ?? servers.filter(s => s.status === 'ONLINE').length
  const configured = winSummary?.winrm_configured ?? servers.filter(s => s.winrm_configured).length
  const aiReadyCount = winSummary?.ai_ready ?? servers.filter(s => s.ai_ready).length
  const exporterRunningCount = winSummary?.windows_exporter_running ?? servers.filter(s => s.windows_exporter_running).length

  return (
    <div className="space-y-6">
      {pageBulkJobId && (
        <BulkJobOverlay
          jobId={pageBulkJobId}
          onDone={() => { setPageBulkJobId(null); refetch() }}
          onDismiss={() => setPageBulkJobId(null)}
        />
      )}
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
            {routeTab === 'events' ? t('win_event_log_title') : routeTab === 'updates' ? t('win_update_title') : t('win_title')}
          </h1>
          <p className="text-slate-400 text-sm mt-0.5">
            {routeTab === 'events'
              ? t('win_event_log_sub')
              : routeTab === 'updates'
              ? t('win_update_sub')
              : t('win_subtitle')}
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
              <span className="text-xs text-slate-400">{t('win_unclassified_vms')}</span>
            </label>
          )}
          {!routeTab && <WinRmAiReadyButton onDone={refetch} />}
          {!routeTab && (
            <WindowsExporterInstallAllButton
              onDone={refetch}
              onJobStart={(jobId) => {
                beginBulkJobModal(jobId)
                setPageBulkJobId(jobId)
              }}
            />
          )}
          <button onClick={() => refetch()}
            className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded-lg transition-colors">
            <RefreshCw size={14} /> {t('refresh_action')}
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
          { label: t('win_stat_detected'), value: winSummary?.confirmed_windows ?? confirmedWindows.length, color: 'text-blue-400' },
          { label: t('win_stat_unknown_os'), value: Math.max(0, (winSummary?.total ?? totalServers) - (winSummary?.confirmed_windows ?? confirmedWindows.length)), color: 'text-amber-400' },
          { label: t('status_online'), value: online, color: 'text-green-400' },
          { label: t('win_stat_winrm'), value: configured, color: 'text-cyan-400' },
          { label: t('ai_ready'), value: aiReadyCount, color: 'text-emerald-400' },
          { label: t('win_stat_exporter'), value: exporterRunningCount, color: 'text-sky-400' },
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
            <span className="text-amber-400/80">{t('win_unclassified_notice')}</span>
          </div>
        </div>
      )}

      {/* Search */}
      <div className="relative max-w-xs">
        <Search size={14} className="absolute left-3 top-2.5 text-slate-500" />
        <input value={search} onChange={e => setSearch(e.target.value)}
          placeholder={t('win_search')} className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-8 pr-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>

      {/* Server List */}
      {isLoading ? (
        <div className="flex items-center justify-center h-40 gap-3 text-slate-400">
          <div className="w-5 h-5 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
          {t('loading')}
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-52 bg-slate-800 border border-slate-700 rounded-xl gap-3">
          <Shield size={40} className="text-slate-600" />
          <p className="text-slate-400 font-medium">{t('win_none')}</p>
          <p className="text-slate-500 text-sm text-center max-w-sm">
            {t('win_none_hint')}<br/>
            <span className="text-slate-600">
              {t('win_none_toggle_hint')}
            </span>
          </p>
        </div>
      ) : (
        <>
        <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700 bg-slate-800/80">
                {[t('col_server'), t('col_type'), t('col_status'), 'OS', `CPU / ${t('memory')}`, 'WinRM', ''].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {filtered.map(srv => {
                const osLabelInput = {
                  os_type: srv.os_type,
                  os_version: srv.os_version || srv.os_type,
                  os_release_id: srv.os_release_id,
                  os_version_id: srv.os_version_id,
                  os_pretty: srv.os_version || srv.os_type,
                }
                return (
                <tr key={srv.id} className="hover:bg-slate-700/30 transition-colors cursor-pointer"
                  onClick={() => setSelected(srv)}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <OsIcon os={osLabelInput} size={28} />
                      <div>
                        <div className="text-sm font-semibold text-white">{srv.name}</div>
                        <div className="text-xs text-slate-500 font-mono">
                          {srv.ip_address || srv.hostname || '—'}
                          {srv.hypervisor_name && <span className="ml-2 text-slate-600">· {srv.hypervisor_name}</span>}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-400 whitespace-nowrap">
                    {(srv.server_type || '').toUpperCase() === 'PHYSICAL' ? t('type_physical')
                      : (srv.server_type || '').toUpperCase() === 'VIRTUAL' ? t('type_virtual')
                        : serverTypeLabel(srv.server_type)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap"><StatusBadge status={srv.status} /></td>
                  <td className="px-4 py-3 text-sm">
                    {srv.confirmed_windows
                      ? (
                        <span className="text-slate-300" title={fullOsLabel(osLabelInput) || undefined}>
                          {shortenOsLabel(osLabelInput)}
                        </span>
                      )
                      : <span className="text-amber-500/70 text-xs italic">{t('win_unknown_os', { os: srv.os_type || t('win_empty') })}</span>
                    }
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="text-xs text-slate-400">
                      {srv.cpu_cores > 0 && <div>{srv.cpu_cores} CPU</div>}
                      {srv.memory_gb > 0 && <div>{srv.memory_gb} GB {t('memory')}</div>}
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
                            <XCircle size={9} /> {t('ai_ready_not')}
                          </span>
                        )}
                        {srv.windows_exporter_running ? (
                          <span className="inline-flex items-center gap-1 text-[10px] text-sky-400">
                            <Activity size={9} /> {t('win_exporter_running')}
                          </span>
                        ) : srv.windows_exporter_installed ? (
                          <span className="inline-flex items-center gap-1 text-[10px] text-amber-500">
                            <Activity size={9} /> {t('win_exporter_stopped')}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[10px] text-slate-600">
                            <Activity size={9} /> {t('win_exporter_none')}
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs text-amber-500">
                        <WifiOff size={11} /> {t('win_unconfigured')}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                    <div className="flex gap-1 justify-end">
                      {!srv.winrm_configured && (
                        <button onClick={() => setCredServer(srv)}
                          className="flex items-center gap-1 px-2.5 py-1 text-xs bg-blue-500/20 text-blue-400 hover:bg-blue-500/30 border border-blue-500/30 rounded-lg transition-colors">
                          <Settings size={11} /> {t('win_setup_winrm')}
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
              )})}
            </tbody>
          </table>
        </div>
        {totalServers > 0 && (
          <div className="flex items-center justify-between text-sm text-slate-400 px-1">
            <span>{(page - 1) * pageSize + 1}–{Math.min(page * pageSize, totalServers)} / {totalServers}</span>
            <div className="flex items-center gap-2">
              <button type="button" disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}
                className="px-3 py-1 rounded-lg bg-slate-800 border border-slate-700 disabled:opacity-40">{t('page_prev')}</button>
              <span>{page} / {totalPages}</span>
              <button type="button" disabled={page >= totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                className="px-3 py-1 rounded-lg bg-slate-800 border border-slate-700 disabled:opacity-40">{t('page_next')}</button>
            </div>
          </div>
        )}
        </>
      )}
      </>
      )}
    </div>
  )
}

export default WindowsServers
