import React, { useState, useEffect, useRef, lazy, Suspense } from 'react'
import {
  ChevronDown, Settings2, Activity, Wifi,
  RefreshCw, CheckCircle2, AlertCircle,
} from 'lucide-react'
const SshTerminalModal = lazy(() => import('../components/SshTerminal'))
import BulkJobOverlay, { persistBulkJobId, restoreActiveBulkJobId } from '../components/BulkJobOverlay'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// ─── Shared Confirm Modal ──────────────────────────────────────────────────────
const ConfirmModal = ({ message, onConfirm, onCancel }: {
  message: string; onConfirm: () => void; onCancel: () => void
}) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
    <div className="bg-cyber-card border border-slate-600 rounded-2xl shadow-2xl p-6 max-w-sm w-full mx-4">
      <div className="flex items-start gap-3 mb-5">
        <div className="w-9 h-9 rounded-full bg-yellow-500/15 border border-yellow-500/30 flex items-center justify-center flex-shrink-0 mt-0.5">
          <span className="text-yellow-400 text-base">⚠</span>
        </div>
        <div>
          <div className="text-sm font-semibold text-white mb-1">Onay Gerekiyor</div>
          <div className="text-sm text-slate-300 leading-relaxed">{message}</div>
        </div>
      </div>
      <div className="flex gap-3 justify-end">
        <button onClick={onCancel} className="px-4 py-2 rounded-lg text-sm text-slate-300 hover:text-white bg-white/[0.07] hover:bg-slate-600 border border-slate-600 transition-colors">İptal</button>
        <button onClick={onConfirm} className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-red-600 hover:bg-red-500 border border-red-500/50 transition-colors">Onayla</button>
      </div>
    </div>
  </div>
)

interface Server {
  id: number
  name: string
  hostname: string
  ip_address: string
  status: string
  os_type: string
  os_version: string
  os_release_id: string
  os_version_id: string
  kernel_version: string
  server_type: string
  cpu_cores: number
  memory_gb: number
  ai_ready: boolean
  hypervisor_id: number | null
  hypervisor_name: string | null
  connection_config: any
  node_exporter?: {
    installed: boolean
    running: boolean
  }
}

// ─── AI Ready Güncelle Butonu ─────────────────────────────────────────────────
const AiReadyUpdateButton: React.FC<{
  onDone: () => void
  onJobStart?: (jobId: string) => void
  asMenuItem?: boolean
}> = ({ onDone, onJobStart, asMenuItem }) => {
  const [loading, setLoading] = React.useState(false)
  const [result, setResult]   = React.useState<string | null>(null)
  const [confirmState, setConfirmState] = React.useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const showConfirm = (msg: string): Promise<boolean> => new Promise(resolve => setConfirmState({ msg, resolve }))

  const handleClick = async () => {
    if (!await showConfirm(
      'Yalnızca Linux sunucularda SSH testi arka planda çalışacak. Bağlanabilenler AI Ready=✅. Windows için Windows → AI Ready Güncelle kullanın. Devam?'
    )) return

    setLoading(true); setResult(null)
    try {
      const r = await fetch(`${API_BASE_URL}/servers/update-ai-ready`, { method: 'POST' })
      const text = await r.text()
      let d: any = null
      try { d = text ? JSON.parse(text) : null } catch {
        setResult(r.status === 504 || r.status === 502 ? 'Zaman aşımı — arka plan devam ediyor olabilir' : `HTTP ${r.status}`)
        return
      }
      if (r.ok) {
        if (d.job_id && onJobStart) {
          onJobStart(d.job_id)
        } else {
          setResult(d.message || `${d.tested ?? 0} kuyrukta`)
          onDone()
          setTimeout(() => { setResult(null); onDone() }, 8000)
        }
      } else {
        setResult(typeof d?.detail === 'string' ? d.detail : 'Hata')
      }
    } finally { setLoading(false) }
  }

  return (
    <>
      {confirmState && <ConfirmModal message={confirmState.msg} onConfirm={() => { confirmState.resolve(true); setConfirmState(null) }} onCancel={() => { confirmState.resolve(false); setConfirmState(null) }} />}
      <button
        onClick={handleClick}
        disabled={loading}
        className={asMenuItem
          ? "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-slate-300 hover:bg-slate-700 hover:text-white transition-colors disabled:opacity-50 text-left"
          : "inline-flex items-center gap-2 px-3 py-2 bg-white/[0.07] border border-slate-600 text-slate-200 rounded-lg hover:bg-slate-600 hover:border-slate-500 transition-all disabled:opacity-50 text-sm"}
        title="Linux SSH ile AI Ready durumunu arka planda güncelle"
      >
        {loading ? (
          <>
            <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin flex-shrink-0" />
            <span>Başlatılıyor...</span>
          </>
        ) : result ? (
          <>
            <CheckCircle2 size={15} className="text-green-400 flex-shrink-0" />
            <span className="truncate text-xs">{result}</span>
          </>
        ) : (
          <>
            <Wifi size={15} className="flex-shrink-0 text-slate-400" />
            <span>AI Ready Güncelle</span>
          </>
        )}
      </button>
    </>
  )
}

// ─── OS Bilgisi Yenile Butonu ──────────────────────────────────────────────────
const OsRefreshButton: React.FC<{
  servers: Server[]
  onDone: () => void
  onJobStart?: (jobId: string) => void
  asMenuItem?: boolean
}> = ({ servers, onDone, onJobStart, asMenuItem }) => {
  const [loading, setLoading] = React.useState(false)
  const [result, setResult]   = React.useState<string | null>(null)
  const [confirmState, setConfirmState] = React.useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const showConfirm = (msg: string): Promise<boolean> => new Promise(resolve => setConfirmState({ msg, resolve }))

  const handleClick = async () => {
    const isWin = (s: Server) => {
      const os = (s.os_type || '').toLowerCase()
      if (os.includes('windows')) return true
      const cfg = s.connection_config || {}
      return !!(cfg.winrm || cfg.protocol === 'winrm')
    }
    const linux = servers.filter(s => !isWin(s))
    const aiReadyIds = linux.filter(s => s.ai_ready).map(s => s.id)
    const ids = aiReadyIds.length > 0 ? aiReadyIds : linux.map(s => s.id)

    if (ids.length === 0) {
      alert('Yenilenecek Linux sunucu yok')
      return
    }

    const confirmed = await showConfirm(
      aiReadyIds.length > 0
        ? `${aiReadyIds.length} AI-Ready Linux sunucuda OS/Kernel bilgisi arka planda güncellenecek. Devam?`
        : `${ids.length} Linux sunucuda OS bilgisi arka planda güncellenecek. Devam?`
    )
    if (!confirmed) return

    setLoading(true); setResult(null)
    try {
      const r = await fetch('/api/v1/servers/refresh-os-info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ server_ids: ids }),
      })
      const text = await r.text()
      let d: any = null
      try { d = text ? JSON.parse(text) : null } catch {
        setResult(r.status === 504 || r.status === 502 ? 'Zaman aşımı' : `HTTP ${r.status}`)
        return
      }
      if (r.ok) {
        if (d.job_id && onJobStart) {
          onJobStart(d.job_id)
        } else {
          setResult(d.message || `${d.updated ?? 0} kuyrukta`)
          onDone()
          setTimeout(() => { setResult(null); onDone() }, 8000)
        }
      } else {
        setResult(typeof d?.detail === 'string' ? d.detail : 'Hata')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      {confirmState && <ConfirmModal message={confirmState.msg} onConfirm={() => { confirmState.resolve(true); setConfirmState(null) }} onCancel={() => { confirmState.resolve(false); setConfirmState(null) }} />}
      <button
        onClick={handleClick}
        disabled={loading}
        className={asMenuItem
          ? "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-slate-300 hover:bg-slate-700 hover:text-white transition-colors disabled:opacity-50 text-left"
          : "inline-flex items-center gap-2 px-3 py-2 bg-white/[0.07] border border-slate-600 text-slate-200 rounded-lg hover:bg-slate-600 hover:border-slate-500 transition-all disabled:opacity-50 text-sm"}
        title="Linux sunucuların OS/Kernel bilgisini SSH ile arka planda güncelle"
      >
        {loading ? (
          <>
            <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin flex-shrink-0" />
            <span>Başlatılıyor...</span>
          </>
        ) : result ? (
          <>
            <CheckCircle2 size={15} className="text-green-400 flex-shrink-0" />
            <span className="truncate text-xs">{result}</span>
          </>
        ) : (
          <>
            <RefreshCw size={15} className="flex-shrink-0 text-slate-400" />
            <span>OS Bilgisini Yenile</span>
          </>
        )}
      </button>
    </>
  )
}

// ─── İşlemler Dropdown ────────────────────────────────────────────────────────
const ActionsDropdown: React.FC<{ servers: Server[]; refetch: () => void }> = ({ servers, refetch }) => {
  const [open, setOpen] = useState(false)
  const [checkLoading, setCheckLoading] = useState(false)
  const [checkResult, setCheckResult] = useState<string | null>(null)
  const [bulkJobId, setBulkJobId] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

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

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const startJob = (jobId: string) => {
    setBulkJobId(jobId)
    setOpen(false)
  }

  const handleCheckHealth = async () => {
    setCheckLoading(true); setCheckResult(null)
    try {
      const r = await fetch(`${API_BASE_URL}/servers/check-health`, { method: 'POST' })
      const d = await r.json()
      if (r.ok) {
        if (d.job_id) {
          startJob(d.job_id)
        } else {
          setCheckResult(`${d.stats?.checked || 0} kontrol · ${d.stats?.updated || 0} güncellendi`)
          refetch()
          setTimeout(() => setCheckResult(null), 5000)
        }
      } else {
        setCheckResult('Hata: ' + (d.detail || '?'))
      }
    } catch { setCheckResult('Bağlantı hatası') }
    finally { setCheckLoading(false) }
  }

  const menuItemCls = "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-slate-300 hover:bg-slate-700 hover:text-white transition-colors disabled:opacity-50 text-left"

  return (
    <div className="relative" ref={ref}>
      {bulkJobId && (
        <BulkJobOverlay
          jobId={bulkJobId}
          onDone={() => refetch()}
          onDismiss={() => {
            setBulkJobId(null)
            refetch()
          }}
        />
      )}
      <button
        onClick={() => setOpen(o => !o)}
        className="inline-flex items-center gap-2 px-3 py-2 bg-slate-800/80 border border-slate-700 text-slate-300 hover:text-white hover:bg-slate-700 rounded-lg transition-all text-sm"
      >
        <Settings2 size={15} />
        <span>İşlemler</span>
        <ChevronDown size={13} className={`transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 bg-slate-800 border border-slate-700/80 rounded-xl shadow-2xl shadow-black/40 z-50 w-56 p-1.5 flex flex-col gap-0.5">
          <p className="text-[10px] text-slate-500 px-3 pt-1 pb-0.5 uppercase tracking-wider font-medium">Toplu İşlemler</p>

          {/* Durumları Kontrol Et */}
          <button
            onClick={handleCheckHealth}
            disabled={checkLoading || !!bulkJobId}
            className={menuItemCls}
          >
            {checkLoading ? (
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin flex-shrink-0" />
            ) : checkResult?.startsWith('Hata') ? (
              <AlertCircle size={15} className="text-red-400 flex-shrink-0" />
            ) : checkResult ? (
              <CheckCircle2 size={15} className="text-green-400 flex-shrink-0" />
            ) : (
              <Activity size={15} className="text-slate-400 flex-shrink-0" />
            )}
            <span className="truncate">{checkResult ?? (checkLoading ? 'Başlatılıyor...' : 'Durumları Kontrol Et')}</span>
          </button>

          <AiReadyUpdateButton onDone={refetch} onJobStart={startJob} asMenuItem />

          <div className="h-px bg-slate-700/60 mx-2 my-0.5" />

          <OsRefreshButton servers={servers} onDone={refetch} onJobStart={startJob} asMenuItem />
        </div>
      )}
    </div>
  )
}

interface MetricsSummary {
  has_node_exporter: boolean
  source?: string | null
  power_state?: string | null
  cpu_percent: number | null
  mem_percent: number | null
  disk_percent: number | null
  load1: number | null
  load5: number | null
  uptime_seconds: number | null
  mem_total_gb: number | null
  mem_used_gb: number | null
  disk_total_gb: number | null
  disk_avail_gb: number | null
  cpu_num?: number | null
}

interface EventGroup {
  event_type: string
  title: string
  severity: string
  server_id: number | null
  server_name: string | null
  event_ids: number[]
  count: number
  latest_created_at: string | null
  resolved?: boolean
  is_acknowledged?: boolean
}

function fmtUptime(seconds: number | null): string {
  if (!seconds) return '-'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}g ${h}s`
  if (h > 0) return `${h}s ${m}dk`
  return `${m}dk`
}

function MetricBar({ label, value, colorClass }: { label: string; value: number | null; colorClass: string }) {
  const v = value ?? 0
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-400 mb-1">
        <span>{label}</span>
        <span className={value !== null ? 'text-white font-medium' : 'text-slate-600'}>{value !== null ? `${value}%` : 'N/A'}</span>
      </div>
      <div className="w-full bg-white/[0.07] rounded-full h-2">
        <div className={`h-2 rounded-full transition-all ${colorClass}`} style={{ width: `${Math.min(v, 100)}%` }} />
      </div>
    </div>
  )
}

const SCOLOR: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  emergency: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
  warning: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  info: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  error: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
}

const TIER_COLORS: Record<string, string> = {
  production: 'bg-red-500/20 text-red-400 border-red-500/30',
  staging: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  development: 'bg-green-500/20 text-green-400 border-green-500/30',
  unknown: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
}
const TIER_LABELS: Record<string, string> = {
  production: '🔴 Production',
  staging: '🟡 Staging',
  development: '🟢 Development',
  unknown: '⚪ Belirsiz',
}
function TierBadge({ tier }: { tier: string }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${TIER_COLORS[tier] || TIER_COLORS['unknown']}`}>
      {TIER_LABELS[tier] || tier}
    </span>
  )
}

export function ServerDetailDrawer({ server, onClose }: { server: Server; onClose: () => void }) {
  const [tab, setTab] = useState<'info' | 'events' | 'perf'>('info')
  const [analyzeText, setAnalyzeText] = useState('')
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const analyzeAbort = React.useRef<AbortController | null>(null)
  const [confirmState, setConfirmState] = React.useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const showConfirm = (msg: string): Promise<boolean> => new Promise(resolve => setConfirmState({ msg, resolve }))

  const { data: metrics, isLoading: metricsLoading } = useQuery<MetricsSummary>({
    queryKey: ['server-metrics-summary', server.id],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/servers/${server.id}/metrics-summary`)
      if (!res.ok) throw new Error('metrics error')
      return res.json()
    },
    refetchInterval: 15000,
    enabled: tab === 'perf',
  })

  const { data: eventsData, isLoading: eventsLoading } = useQuery<{ total: number; groups: EventGroup[] }>({
    queryKey: ['server-events', server.id],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/events/grouped?server_id=${server.id}&resolved=false&limit=30&sort_by=latest_created_at&sort_dir=desc&platform=linux`)
      if (!res.ok) return { total: 0, groups: [] }
      return res.json()
    },
    refetchInterval: 30000,
    enabled: tab === 'events',
  })

  // Son güncelleme bilgisi
  const { data: updateHistory } = useQuery<{ history: any[]; pending_reboot: boolean }>({
    queryKey: ['server-update-history', server.id],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/updates/server-history/${server.id}`)
      if (!r.ok) return { history: [], pending_reboot: false }
      return r.json()
    },
    enabled: tab === 'info',
  })

  const { data: vmSnapshots, refetch: refetchSnapshots } = useQuery<{
    tracked: { id: number; snapshot_name: string; status: string; retention: string; created_at: string; expires_at: string | null }[]
    external: { id: string; name: string; description?: string; created?: string; status?: string }[]
    can_snapshot: boolean
    hypervisor_connected: boolean
    vm_id_missing: boolean
    platform?: string
  }>({
    queryKey: ['server-vm-snapshots', server.id],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/snapshots/server/${server.id}`)
      if (!r.ok) return { tracked: [], external: [], can_snapshot: false, hypervisor_connected: false, vm_id_missing: false }
      return r.json()
    },
    enabled: tab === 'info' && !!server.hypervisor_id,
  })

  const [snapCreating, setSnapCreating] = useState(false)
  const [snapRetention, setSnapRetention] = useState('1w')
  const [vmSearching, setVmSearching] = useState(false)

  const { data: vmDetails, refetch: refetchVmDetails } = useQuery<{
    hypervisor_vm_id?: string
    vm_name?: string
    vm_guest_hostname?: string
    vm_guest_ip?: string
    vm_cpu_count?: number
    vm_memory_mb?: number
    vm_disk_gb?: number
    vm_power_state?: string
    vm_tools_status?: string
    vm_network_info?: Array<{ name: string; mac: string; ips: Array<{ address: string; version: string }> }>
    vm_cluster?: string
    vm_datastore?: string
    vm_hardware_version?: string
    vm_last_sync?: string
    can_snapshot: boolean
  }>({
    queryKey: ['server-vm-details', server.id],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/snapshots/server/${server.id}/vm-details`)
      if (!r.ok) return { can_snapshot: false }
      return r.json()
    },
    enabled: tab === 'info' && !!server.hypervisor_id,
    refetchInterval: false,
  })

  const handleSearchVm = async () => {
    setVmSearching(true)
    try {
      const r = await fetch(`${API_BASE_URL}/snapshots/server/${server.id}/search-vm`, { method: 'POST' })
      await r.json().catch(() => ({}))
      refetchVmDetails()
      refetchSnapshots()
    } catch { /* ignore */ } finally {
      setVmSearching(false)
    }
  }

  const startAnalyze = async () => {
    analyzeAbort.current?.abort()
    const ctrl = new AbortController()
    analyzeAbort.current = ctrl
    setAnalyzeText('')
    setIsAnalyzing(true)
    const model = localStorage.getItem('chat_selected_model') || 'llama3.2:3b'
    const metricsCtx = metrics ? `CPU: ${metrics.cpu_percent ?? 'N/A'}%, RAM: ${metrics.mem_percent ?? 'N/A'}%, Disk: ${metrics.disk_percent ?? 'N/A'}%, Load: ${metrics.load1 ?? 'N/A'}` : ''
    const prompt = `${server.name} (${server.ip_address}) sunucusunun genel durumunu analiz et. ${metricsCtx ? `Anlık metrikler: ${metricsCtx}.` : ''} Bu sunucuyla ilgili dikkat edilmesi gereken noktaları, önerileri ve varsa performans iyileştirmelerini belirt.`
    try {
      const res = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: prompt, use_rag: true, model }),
        signal: ctrl.signal,
      })
      if (!res.ok || !res.body) throw new Error()
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = '', acc = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const chunk = JSON.parse(line.slice(6))
            if (chunk.token) { acc += chunk.token; setAnalyzeText(acc) }
            if (chunk.done) setIsAnalyzing(false)
          } catch {}
        }
      }
    } catch (e: any) {
      if (e?.name !== 'AbortError') setAnalyzeText('❌ Analiz başarısız.')
    } finally { setIsAnalyzing(false) }
  }

  const sshUser = server.connection_config?.username
  const cpuColor = (v: number | null) => v === null ? 'bg-slate-600' : v > 85 ? 'bg-red-500' : v > 60 ? 'bg-yellow-500' : 'bg-green-500'
  const memColor = (v: number | null) => v === null ? 'bg-slate-600' : v > 85 ? 'bg-red-500' : v > 70 ? 'bg-amber-500' : 'bg-blue-500'
  const diskColor = (v: number | null) => v === null ? 'bg-slate-600' : v > 85 ? 'bg-red-500' : v > 70 ? 'bg-amber-500' : 'bg-blue-500'

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="w-full max-w-xl bg-cyber-deep border-l border-white/[0.06] flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-white/[0.06] bg-cyber-card/50">
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${server.status === 'ONLINE' ? 'bg-gradient-to-br from-green-500 to-green-600' : 'bg-gradient-to-br from-slate-600 to-slate-700'}`}>
            <span className="text-xs font-bold text-blue-400">SRV</span>
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-white font-semibold text-base truncate">{server.name}</h2>
            <div className="flex items-center gap-2 mt-0.5 flex-wrap">
              <p className="text-slate-400 text-xs font-mono">{server.ip_address}</p>
              {server.hypervisor_name && (
                <span className="text-xs text-slate-500 bg-white/[0.07]/50 px-1.5 py-0.5 rounded">
                  ☁ {server.hypervisor_name}
                </span>
              )}
            </div>
          </div>
          <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${server.status === 'ONLINE' ? 'bg-green-500/20 text-green-400 border-green-500/30' : 'bg-red-500/20 text-red-400 border-red-500/30'}`}>
            ● {server.status}
          </span>
          {/* SSH butonu detay headerında — sadece Linux */}
          {server.status === 'ONLINE' && server.ip_address && !((server.os_type || '').toLowerCase().includes('windows')) && (
            <button
              onClick={() => {
                const w = window.open(
                  `/terminal/${server.id}?name=${encodeURIComponent(server.name)}&ip=${encodeURIComponent(server.ip_address)}`,
                  `ssh-${server.id}`,
                  'width=1200,height=700,resizable=yes,scrollbars=no,menubar=no,toolbar=no,location=no,status=no'
                )
                if (!w) alert('Popup engellendi — tarayıcı ayarlarınızdan popup iznini açın.')
              }}
              className="flex items-center gap-1 px-2.5 py-1 text-xs bg-green-700/40 hover:bg-green-700 text-green-300 rounded-lg transition-colors font-mono flex-shrink-0"
              title="SSH Terminal"
            >
              <span>⌨</span> SSH
            </button>
          )}
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none flex-shrink-0">&times;</button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-white/[0.06] bg-cyber-card/30">
          {([['info', 'Bilgi'], ['perf', 'Performans'], ['events', 'Eventler']] as const).map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)}
              className={`px-4 py-2.5 text-xs font-medium transition-colors border-b-2 ${tab === id ? 'border-blue-500 text-blue-400' : 'border-transparent text-slate-400 hover:text-white'}`}>
              {label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">

          {/* ── INFO TAB ── */}
          {tab === 'info' && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                {[
                  ['Sunucu Adı', server.name],
                  ['IP Adresi', server.ip_address || '-'],
                  ['Hostname', server.hostname || '-'],
                  ...(server.hypervisor_name ? [['Hypervisor', `☁ ${server.hypervisor_name}`]] : []),
                  ['Tip', server.server_type || '-'],
                  ['OS Dağıtım', server.os_release_id ? server.os_release_id.toUpperCase() : (server.os_type || '-')],
                  ['OS Sürüm', server.os_version_id ? `${server.os_version_id} — ${server.os_version || ''}` : (server.os_version || '-')],
                  ['Kernel', server.kernel_version || '-'],
                  ['CPU', server.cpu_cores ? `${server.cpu_cores} çekirdek` : '-'],
                  ['RAM', server.memory_gb ? `${server.memory_gb} GB` : '-'],
                  ['SSH Kullanıcı', sshUser || '-'],
                  ['AI Ready', '__AI_READY_TOGGLE__'],
                  ['Ortam Tieri', '__TIER_SELECT__'],
                  ['Node Exporter', server.node_exporter?.running ? 'Çalışıyor' : server.node_exporter?.installed ? 'Kurulu/Durdurulmuş' : 'Kurulu Değil'],
                ].map(([label, value]) => (
                  <div key={label} className="bg-cyber-card/50 rounded-lg p-3 border border-white/[0.06]/50">
                    <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-0.5">{label}</p>
                    {value === '__AI_READY_TOGGLE__' ? (
                      <div className="flex items-center justify-between mt-0.5">
                        <span className={`text-sm font-medium ${server.ai_ready ? 'text-green-400' : 'text-slate-400'}`}>
                          {server.ai_ready ? 'AI Ready' : 'AI Ready Değil'}
                        </span>
                        <button
                          onClick={async () => {
                            const newVal = !server.ai_ready
                            await fetch(`${API_BASE_URL}/servers/${server.id}`, {
                              method: 'PUT',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ ai_ready: newVal }),
                            })
                            onClose()
                          }}
                          className={`text-xs px-2 py-0.5 rounded-lg border transition-colors ${
                            server.ai_ready
                              ? 'text-red-400 border-red-500/40 hover:bg-red-500/10'
                              : 'text-green-400 border-green-500/40 hover:bg-green-500/10'
                          }`}
                        >
                          {server.ai_ready ? 'Kaldır' : 'Ekle'}
                        </button>
                      </div>
                    ) : value === '__TIER_SELECT__' ? (
                      <div className="flex items-center justify-between mt-0.5">
                        <TierBadge tier={(server as any).tier || 'unknown'} />
                        <select
                          className="text-xs bg-gray-700 border border-gray-600 text-gray-200 rounded px-1.5 py-0.5"
                          defaultValue={(server as any).tier || 'unknown'}
                          onChange={async (e) => {
                            await fetch(`${API_BASE_URL}/baseline/servers/${server.id}/tier`, {
                              method: 'PATCH',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ tier: e.target.value }),
                            })
                          }}
                        >
                          <option value="production">Production</option>
                          <option value="staging">Staging</option>
                          <option value="development">Development</option>
                          <option value="unknown">Belirsiz</option>
                        </select>
                      </div>
                    ) : (
                      <p className="text-sm text-white font-medium break-all">{value}</p>
                    )}
                  </div>
                ))}
              </div>

              {/* Son Güncelleme Bilgisi */}
              {updateHistory && (updateHistory.history.length > 0 || updateHistory.pending_reboot) && (
                <div className={`rounded-xl border p-4 space-y-2 ${updateHistory.pending_reboot ? 'bg-yellow-500/10 border-yellow-500/30' : 'bg-cyber-card/50 border-white/[0.06]'}`}>
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-medium text-white">Güncelleme Geçmişi</h3>
                    {updateHistory.pending_reboot && (
                      <span className="text-xs bg-yellow-500/20 text-yellow-300 border border-yellow-500/30 px-2 py-0.5 rounded-full animate-pulse">
                        Reboot Gerekiyor
                      </span>
                    )}
                  </div>
                  {updateHistory.history.slice(0, 3).map((h: any, i: number) => (
                    <div key={i} className="flex items-center gap-3 text-xs">
                      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                        h.status === 'completed' ? 'bg-green-400' :
                        h.status === 'failed'    ? 'bg-red-400' : 'bg-slate-400'
                      }`} />
                      <div className="flex-1 min-w-0">
                        <span className="text-slate-200 font-medium">{h.plan_name}</span>
                        <span className="text-slate-500 ml-2">{h.update_type}</span>
                      </div>
                      <span className="text-slate-400 flex-shrink-0">
                        {h.packages_updated} paket
                      </span>
                      {h.reboot_required && !h.rebooted && (
                        <span className="text-yellow-400 flex-shrink-0 font-bold">!</span>
                      )}
                      <span className="text-slate-500 flex-shrink-0">
                        {h.completed_at ? new Date(h.completed_at).toLocaleDateString('tr-TR') : '—'}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* VM Detayları Kartı */}
              {server.hypervisor_id && (
                <div className="bg-cyber-card/50 rounded-xl border border-white/[0.06] p-4 space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-sm font-medium text-white flex items-center gap-1.5">
                      VM Detayları
                      {vmDetails?.vm_last_sync && (
                        <span className="text-[10px] text-slate-500 font-normal">
                          son sync: {new Date(vmDetails.vm_last_sync).toLocaleString('tr-TR')}
                        </span>
                      )}
                    </h3>
                    {/* Manuel yenileme — otomatik sync 2 saatte bir, gerekirse elle çalıştırılır */}
                    <button
                      onClick={handleSearchVm}
                      disabled={vmSearching}
                      className="flex items-center gap-1 px-2.5 py-1 text-xs rounded border border-slate-600/50 bg-white/[0.04] text-slate-400 hover:text-slate-200 hover:bg-white/[0.05] transition-colors disabled:opacity-50"
                      title="VM bilgilerini hypervisor'dan yenile"
                    >
                      {vmSearching
                        ? <><span className="w-2.5 h-2.5 border border-current border-t-transparent rounded-full animate-spin" /> Yenileniyor...</>
                        : '↻ Yenile'
                      }
                    </button>
                  </div>

                  {/* VM detay grid */}
                  {vmDetails?.hypervisor_vm_id ? (
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                      {[
                        { label: 'VM ID',       val: vmDetails.hypervisor_vm_id },
                        { label: 'VM Adı',      val: vmDetails.vm_name },
                        { label: 'Guest Host',  val: vmDetails.vm_guest_hostname },
                        { label: 'Guest IP',    val: vmDetails.vm_guest_ip },
                        { label: 'vCPU',        val: vmDetails.vm_cpu_count != null ? `${vmDetails.vm_cpu_count} core` : undefined },
                        { label: 'RAM',         val: vmDetails.vm_memory_mb != null ? `${(vmDetails.vm_memory_mb / 1024).toFixed(1)} GB` : undefined },
                        { label: 'Disk',        val: vmDetails.vm_disk_gb != null ? `${vmDetails.vm_disk_gb} GB` : undefined },
                        { label: 'Cluster',     val: vmDetails.vm_cluster },
                        { label: 'Datastore',   val: vmDetails.vm_datastore },
                        { label: 'HW Versiyonu',val: vmDetails.vm_hardware_version },
                      ].map(({ label, val }) => val ? (
                        <div key={label} className="flex gap-1.5">
                          <span className="text-slate-500 flex-shrink-0 w-24">{label}</span>
                          <span className="text-slate-200 truncate font-mono text-[11px]">{val}</span>
                        </div>
                      ) : null)}

                      {/* Güç durumu */}
                      {vmDetails.vm_power_state && (
                        <div className="flex gap-1.5 col-span-2">
                          <span className="text-slate-500 w-24 flex-shrink-0">Güç Durumu</span>
                          <span className={`font-medium ${
                            ['up', 'poweredon', 'running'].includes((vmDetails.vm_power_state || '').toLowerCase())
                              ? 'text-green-400' : 'text-red-400'
                          }`}>
                            {vmDetails.vm_power_state}
                          </span>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500 italic">
                      VM ID henüz kaydedilmemiş. "VM Ara &amp; Kaydet" ile hypervisor'dan çekin.
                    </p>
                  )}

                  {/* Ağ adaptörleri */}
                  {(vmDetails?.vm_network_info?.length ?? 0) > 0 && (
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Ağ Adaptörleri</p>
                      <div className="space-y-1">
                        {vmDetails!.vm_network_info!.map((nic, i) => (
                          <div key={i} className="flex items-start gap-2 text-xs bg-white/[0.02] rounded px-2 py-1.5">
                            <span className="text-slate-400 flex-shrink-0">●</span>
                            <div className="min-w-0">
                              <span className="text-slate-300">{nic.name || `NIC ${i + 1}`}</span>
                              {nic.mac && <span className="text-slate-500 ml-2 font-mono text-[10px]">{nic.mac}</span>}
                              {nic.ips?.map(ip => (
                                <div key={ip.address} className="text-cyan-400/80 font-mono text-[10px]">
                                  {ip.address} <span className="text-slate-600">{ip.version}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* VM Snapshot */}
              {server.hypervisor_id && (
                <div className="bg-cyber-card/50 rounded-xl border border-white/[0.06] p-4 space-y-3">
                  {/* Header */}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-medium text-white">📸 VM Snapshot</h3>
                      {vmSnapshots?.platform && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.07] text-slate-400 uppercase">
                          {vmSnapshots.platform}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {/* Retention seçici — hypervisor_id varsa her zaman göster */}
                      {vmSnapshots?.hypervisor_connected !== false && server.hypervisor_id && (
                        <select
                          value={snapRetention}
                          onChange={e => setSnapRetention(e.target.value)}
                          className="text-xs bg-white/[0.07] border border-slate-600 text-slate-300 rounded px-1.5 py-0.5"
                        >
                          <option value="1d">1 Gün</option>
                          <option value="1w">1 Hafta</option>
                          <option value="1m">1 Ay</option>
                          <option value="indefinite">Süresiz</option>
                        </select>
                      )}
                      {/* Snapshot Al butonu — VM ID yoksa backend otomatik arar */}
                      {server.hypervisor_id && (
                        <button
                          disabled={snapCreating}
                          title="Snapshot al (arka planda çalışır)"
                          onClick={async () => {
                            setSnapCreating(true)
                            try {
                              const r = await fetch(`${API_BASE_URL}/snapshots/server/${server.id}`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ retention: snapRetention, name_prefix: 'DTT' }),
                              })
                              const data = await r.json().catch(() => ({}))
                              if (r.ok) {
                                // Accepted — backend'de arka planda devam ediyor
                                refetchSnapshots()
                                // Pending kaydı görmek için 5sn'de bir polling yap
                                const poll = setInterval(() => { refetchSnapshots() }, 5000)
                                setTimeout(() => clearInterval(poll), 5 * 60 * 1000)
                              } else {
                                alert(data.detail || 'Snapshot başlatılamadı')
                              }
                            } finally {
                              // Buton 3sn sonra tekrar aktif olsun
                              setTimeout(() => setSnapCreating(false), 3000)
                            }
                          }}
                          className="flex items-center gap-1 px-3 py-1 text-xs rounded border transition-colors disabled:opacity-50 bg-cyan-700/40 text-cyan-300 border-cyan-500/30 hover:bg-cyan-700/50"
                        >
                          {snapCreating
                            ? <><span className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" /> Başlatılıyor...</>
                            : '+ Snapshot Al'
                          }
                        </button>
                      )}
                    </div>
                  </div>

                  {/* VM ID yok uyarısı */}
                  {vmSnapshots?.vm_id_missing && !snapCreating && (
                    <div className="flex items-start gap-2 text-xs text-yellow-400/80 bg-yellow-500/5 border border-yellow-500/20 rounded-lg px-3 py-2">
                      <span className="flex-shrink-0 mt-0.5">⚠</span>
                      <span>VM ID bilinmiyor. "Ara &amp; Snapshot Al" tıklandığında vCenter/oVirt üzerinde arama yapılır ve ID kaydedilir.</span>
                    </div>
                  )}

                  {/* Hypervisor bağlı değil */}
                  {!vmSnapshots?.hypervisor_connected && (
                    <p className="text-xs text-slate-500">Fiziksel sunucu — snapshot desteklenmiyor.</p>
                  )}

                  {/* Uygulama tarafından takip edilen snapshotlar */}
                  {(vmSnapshots?.tracked?.length ?? 0) > 0 && (
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-1.5">Kayıtlı</p>
                      <div className="space-y-1.5 max-h-48 overflow-y-auto">
                        {vmSnapshots!.tracked.map(s => (
                          <div key={s.id} className={`flex items-center gap-2 text-xs rounded-lg px-3 py-2 ${
                            s.status === 'pending' ? 'bg-yellow-900/20 border border-yellow-700/30'
                            : s.status === 'failed' ? 'bg-red-900/20 border border-red-700/30'
                            : 'bg-white/[0.07]/30'
                          }`}>
                            {s.status === 'pending'
                              ? <span className="w-3 h-3 border border-yellow-400/60 border-t-yellow-400 rounded-full animate-spin flex-shrink-0" />
                              : <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                                  s.status === 'active' ? 'bg-cyan-400'
                                  : s.status === 'failed' ? 'bg-red-400'
                                  : 'bg-slate-400'
                                }`} />
                            }
                            <div className="flex-1 min-w-0">
                              <div className="text-slate-200 truncate font-mono">{s.snapshot_name}</div>
                              <div className="text-slate-500 text-[10px] flex items-center gap-1.5">
                                {s.status === 'pending' && <span className="text-yellow-400">vCenter'da oluşturuluyor...</span>}
                                {s.status === 'failed' && <span className="text-red-400">Başarısız</span>}
                                <span>{s.retention} · {new Date(s.created_at).toLocaleString('tr-TR')}</span>
                                {s.expires_at && <span>· bitiş {new Date(s.expires_at).toLocaleDateString('tr-TR')}</span>}
                              </div>
                            </div>
                            {s.status !== 'pending' && (
                              <button
                                onClick={async () => {
                                  if (!await showConfirm('Snapshot silinsin mi? (Hypervisor\'dan da kaldırılır)')) return
                                  const r = await fetch(`${API_BASE_URL}/snapshots/${s.id}`, { method: 'DELETE' })
                                  if (r.ok) refetchSnapshots()
                                  else { const e = await r.json().catch(() => ({})); alert(e.detail || 'Silinemedi') }
                                }}
                                className="text-red-400 hover:text-red-300 px-2 py-0.5 rounded hover:bg-red-500/10 flex-shrink-0"
                                title="Snapshot'u sil"
                              >
                                Sil
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Hypervisor'dan doğrudan okunan harici snapshotlar */}
                  {(vmSnapshots?.external?.length ?? 0) > 0 && (
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-1.5">Hypervisor'daki Tüm Snapshotlar</p>
                      <div className="space-y-1.5 max-h-40 overflow-y-auto">
                        {vmSnapshots!.external.map((s, i) => (
                          <div key={s.id || i} className="flex items-center gap-2 text-xs bg-white/[0.02] rounded-lg px-3 py-2 border border-white/[0.04]">
                            <span className="text-slate-400 flex-shrink-0">🔖</span>
                            <div className="flex-1 min-w-0">
                              <div className="text-slate-300 truncate">{s.name}</div>
                              {s.description && <div className="text-slate-500 text-[10px] truncate">{s.description}</div>}
                              {s.created && <div className="text-slate-500 text-[10px]">{new Date(s.created).toLocaleString('tr-TR')}</div>}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Hiç snapshot yok */}
                  {(vmSnapshots?.tracked?.length ?? 0) === 0 && (vmSnapshots?.external?.length ?? 0) === 0 && vmSnapshots?.hypervisor_connected && (
                    <p className="text-xs text-slate-500">Kayıtlı snapshot yok.</p>
                  )}
                </div>
              )}

              {/* AI Analiz */}
              <div className="bg-cyber-card/50 rounded-xl border border-white/[0.06] p-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-medium text-white">AI Analiz</h3>
                  <button onClick={startAnalyze} disabled={isAnalyzing}
                    className="px-3 py-1 text-xs bg-blue-600/30 text-blue-300 border border-blue-500/30 rounded hover:bg-blue-600/40 disabled:opacity-50">
                    {isAnalyzing ? 'Analiz ediliyor...' : analyzeText ? 'Yeniden' : 'Analiz Et'}
                  </button>
                </div>
                {analyzeText ? (
                  <div className="prose prose-invert prose-sm max-w-none text-slate-200 text-xs">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{analyzeText}</ReactMarkdown>
                    {isAnalyzing && <span className="inline-block w-1.5 h-3 bg-blue-400 animate-pulse ml-0.5 rounded-sm" />}
                  </div>
                ) : isAnalyzing ? (
                  <div className="flex items-center gap-2 text-slate-400 text-xs">
                    <div className="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                    <span>AI analiz yapıyor...</span>
                  </div>
                ) : (
                  <p className="text-slate-500 text-xs">Sunucu hakkında AI analizi başlatmak için yukarıdaki butona tıklayın.</p>
                )}
              </div>
            </div>
          )}

          {/* ── PERF TAB ── */}
          {tab === 'perf' && (
            <div className="space-y-4">
              {metricsLoading ? (
                <div className="flex items-center gap-2 text-slate-400 text-sm py-8 justify-center">
                  <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                  <span>Metrikler yükleniyor...</span>
                </div>
              ) : (!metrics?.has_node_exporter && !metrics?.source) ? (
                <div className="text-center py-10 text-slate-500">
                  <p className="text-3xl mb-3">📡</p>
                  <p className="text-sm">Node Exporter kurulu değil ve vCenter'dan veri alınamadı.</p>
                  {server.server_type === 'VIRTUAL' && (
                    <p className="text-xs text-slate-600 mt-1">Ayarlar → Hypervisors'dan vCenter bağlantısını kontrol edin.</p>
                  )}
                </div>
              ) : (
                <>
                  {/* Data source badge */}
                  <div className="flex items-center gap-2 text-xs">
                    {metrics.source === 'vcenter' ? (
                      <span className="px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-400 border border-blue-500/30">vCenter</span>
                    ) : metrics.source === 'prometheus' ? (
                      <span className="px-2 py-0.5 rounded-full bg-green-500/20 text-green-400 border border-green-500/30">Prometheus / Node Exporter</span>
                    ) : null}
                    {metrics.power_state && (
                      <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${metrics.power_state === 'POWERED_ON' ? 'bg-green-500/20 text-green-400 border-green-500/30' : 'bg-red-500/20 text-red-400 border-red-500/30'}`}>
                        {metrics.power_state === 'POWERED_ON' ? 'Açık' : 'Kapalı'}
                      </span>
                    )}
                  </div>

                  {/* Gauge cards */}
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { label: 'CPU', value: metrics.cpu_percent, icon: '', color: 'text-yellow-400' },
                      { label: 'RAM', value: metrics.mem_percent, icon: '', color: 'text-blue-400' },
                      { label: 'Disk', value: metrics.disk_percent, icon: '', color: 'text-blue-400' },
                    ].map(({ label, value, icon, color }) => (
                      <div key={label} className="bg-cyber-card/50 rounded-xl border border-white/[0.06] p-3 text-center">
                        <p className={`text-2xl font-bold ${value !== null ? (value > 85 ? 'text-red-400' : value > 60 ? 'text-yellow-400' : 'text-green-400') : 'text-slate-600'}`}>
                          {value !== null ? `${value}%` : 'N/A'}
                        </p>
                        <p className={`text-xs mt-1 ${color}`}>{icon} {label}</p>
                      </div>
                    ))}
                  </div>

                  {/* Progress bars */}
                  <div className="bg-cyber-card/50 rounded-xl border border-white/[0.06] p-4 space-y-3">
                    <MetricBar label="CPU Kullanımı" value={metrics.cpu_percent} colorClass={cpuColor(metrics.cpu_percent)} />
                    <MetricBar label={`RAM  ${metrics.mem_used_gb != null ? `(${metrics.mem_used_gb}/${metrics.mem_total_gb} GB)` : ''}`} value={metrics.mem_percent} colorClass={memColor(metrics.mem_percent)} />
                    <MetricBar label={`Disk  ${metrics.disk_avail_gb != null ? `(${metrics.disk_avail_gb} GB boş / ${metrics.disk_total_gb} GB)` : ''}`} value={metrics.disk_percent} colorClass={diskColor(metrics.disk_percent)} />
                  </div>

                  {/* Extra info */}
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      metrics.source === 'vcenter'
                        ? ['vCPU Sayısı', metrics.cpu_num !== null ? String(metrics.cpu_num) : '-']
                        : ['Load 1m', metrics.load1 !== null ? String(metrics.load1) : '-'],
                      metrics.source === 'vcenter'
                        ? ['RAM (Toplam)', metrics.mem_total_gb !== null ? `${metrics.mem_total_gb} GB` : '-']
                        : ['Load 5m', metrics.load5 !== null ? String(metrics.load5) : '-'],
                      ['Uptime', fmtUptime(metrics.uptime_seconds)],
                    ].map(([label, value]) => (
                      <div key={label} className="bg-cyber-card/50 rounded-lg p-3 border border-white/[0.06]/50 text-center">
                        <p className="text-xs text-slate-500 mb-0.5">{label}</p>
                        <p className="text-sm font-medium text-white">{value}</p>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {/* ── EVENTS TAB ── */}
          {tab === 'events' && (
            <div className="space-y-2">
              {eventsLoading ? (
                <div className="flex items-center gap-2 text-slate-400 text-sm py-8 justify-center">
                  <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                  <span>Eventler yükleniyor...</span>
                </div>
              ) : !eventsData?.groups?.length ? (
                <div className="text-center py-10 text-slate-500">
                  <p className="text-2xl font-bold text-green-400 mb-3">✓</p>
                  <p className="text-sm">Bu sunucuya ait aktif event bulunmuyor.</p>
                </div>
              ) : (
                eventsData.groups.map((grp, i) => (
                  <div key={i} className="bg-cyber-card/50 rounded-lg border border-white/[0.06]/50 p-3">
                    <div className="flex items-start gap-2">
                      <span className={`mt-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold border flex-shrink-0 ${SCOLOR[grp.severity] || SCOLOR.info}`}>
                        {grp.severity}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs text-slate-200 break-words leading-snug">{grp.title}</p>
                        <div className="flex gap-3 mt-1">
                          <span className="text-[10px] text-slate-500">{grp.event_type}</span>
                          <span className="text-[10px] text-slate-500">{grp.count}×</span>
                          {grp.latest_created_at && (
                            <span className="text-[10px] text-slate-500">
                              {new Date(grp.latest_created_at).toLocaleString('tr-TR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

        </div>
      </div>
      {confirmState && <ConfirmModal message={confirmState.msg} onConfirm={() => { confirmState.resolve(true); setConfirmState(null) }} onCancel={() => { confirmState.resolve(false); setConfirmState(null) }} />}
    </div>
  )
}


const Servers: React.FC = () => {
  const [selectedServer, setSelectedServer] = useState<Server | null>(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [confirmState, setConfirmState] = useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const showConfirm = (msg: string): Promise<boolean> => new Promise(resolve => setConfirmState({ msg, resolve }))
  const [ipFilter, setIpFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [showOffline, setShowOffline] = useState(false)
  const [aiReadyFilter, setAiReadyFilter] = useState<string>('all') // Tümü — Linux + Windows + diğer
  const [typeFilter, setTypeFilter] = useState<string>('all') // all, VIRTUAL, PHYSICAL
  const [osFilter, setOsFilter] = useState<string>('all') // all, linux, windows, other
  const [nodeExporterFilter, setNodeExporterFilter] = useState<string>('all') // all, installed, running, not_installed

  const [sortKey, setSortKey] = useState<string>('name')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')
  const [sshTarget, setSshTarget] = useState<{id: number; name: string; ip: string} | null>(null)

  // Kolon genişlikleri (px)
  const [colWidths, setColWidths] = useState<number[]>([260, 120, 240, 140, 180, 120])

  // Resize handler
  const resizingCol = React.useRef<{col: number; startX: number; startW: number} | null>(null)
  const onResizeMouseDown = (col: number, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    resizingCol.current = { col, startX: e.clientX, startW: colWidths[col] }
    const onMove = (ev: MouseEvent) => {
      if (!resizingCol.current) return
      const delta = ev.clientX - resizingCol.current.startX
      const newW = Math.max(60, resizingCol.current.startW + delta)
      setColWidths(prev => { const next = [...prev]; next[resizingCol.current!.col] = newW; return next })
    }
    const onUp = () => { resizingCol.current = null; document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp) }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }
  const queryClient = useQueryClient()

  // Önce sunucu listesini al (Node Exporter durumu olmadan)
  const { data: servers = [], isLoading, isFetching, isError, error, refetch } = useQuery<Server[]>({
    queryKey: ['servers', 'linux'],
    queryFn: async () => {
      // Bu sayfa Linux modülü altında — sadece Linux (Windows olmayan) sunucular gösterilir.
      const response = await fetch(`${API_BASE_URL}/servers/?platform=linux`)
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

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await fetch(`${API_BASE_URL}/servers/${id}`, { method: 'DELETE' })
      if (!response.ok) throw new Error('Failed to delete server')
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] })
    }
  })

  const toggleSort = (key: string) => {
    if (sortKey === key) {
      setSortDirection(prev => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDirection('asc')
    }
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
    
    // Status filtresi:
    // showOffline=false → OFFLINE gizle (ONLINE + WARNING + diğerleri görünür)
    // showOffline=true  → hepsi görünür (OFFLINE dahil)
    const matchesStatus = showOffline
      ? (statusFilter === 'all' || server.status === statusFilter)
      : (server.status !== 'OFFLINE' && (statusFilter === 'all' || server.status === statusFilter))
    
    const matchesAiReady = aiReadyFilter === 'all' || 
      (aiReadyFilter === 'true' && server.ai_ready) ||
      (aiReadyFilter === 'false' && !server.ai_ready)
    
    const matchesType = typeFilter === 'all' || server.server_type === typeFilter

    const osTypeLow = (server.os_type || '').toLowerCase()
    const matchesOs = osFilter === 'all' ||
      (osFilter === 'linux' && !osTypeLow.includes('windows') && (osTypeLow.includes('linux') || osTypeLow.includes('rhel') || osTypeLow.includes('ol') || osTypeLow.includes('ubuntu') || osTypeLow.includes('centos') || osTypeLow.includes('rocky') || osTypeLow.includes('sles') || server.os_release_id)) ||
      (osFilter === 'other' && !osTypeLow.includes('windows') && !osTypeLow.includes('linux') && !osTypeLow.includes('rhel') && !osTypeLow.includes('ol') && !osTypeLow.includes('ubuntu') && !osTypeLow.includes('centos') && !osTypeLow.includes('rocky') && !osTypeLow.includes('sles') && !server.os_release_id)

    const matchesNodeExporter = nodeExporterFilter === 'all' ||
      (nodeExporterFilter === 'installed' && server.node_exporter?.installed) ||
      (nodeExporterFilter === 'running' && server.node_exporter?.running) ||
      (nodeExporterFilter === 'not_installed' && !server.node_exporter?.installed)

    return matchesSearch && matchesIp && matchesStatus && matchesAiReady && matchesType && matchesOs && matchesNodeExporter
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

  // OS platform tabs — bu sayfa Linux modülüne ait; API zaten ?platform=linux ile
  // Windows sunucuları hariç tutuyor, dolayısıyla burada Windows sekmesi/filtresi
  // gösterilmez (bkz. Windows Sunucular sayfası: /windows).
  const platformCounts = {
    all: servers.length,
    linux: servers.filter(s => !(s.os_type || '').toLowerCase().includes('windows')).length,
  }

  return (
    <>
      {confirmState && <ConfirmModal message={confirmState.msg} onConfirm={() => { confirmState.resolve(true); setConfirmState(null) }} onCancel={() => { confirmState.resolve(false); setConfirmState(null) }} />}
    <div className="space-y-6">
      {/* Platform tabs */}
      <div className="flex items-center gap-1 bg-slate-800/60 rounded-xl p-1 w-fit border border-slate-700/60">
        {([
          { key: 'all', label: 'Tümü', count: platformCounts.all },
          { key: 'linux', label: 'Linux', count: platformCounts.linux },
        ] as const).map(tab => (
          <button key={tab.key}
            onClick={() => setOsFilter(tab.key === 'all' ? 'all' : tab.key)}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              (tab.key === 'all' && osFilter === 'all') || (tab.key !== 'all' && osFilter === tab.key)
                ? 'bg-blue-600 text-white shadow'
                : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
            }`}>
            {tab.label}
            <span className={`text-[11px] px-1.5 py-0.5 rounded-full ${
              (tab.key === 'all' && osFilter === 'all') || (tab.key !== 'all' && osFilter === tab.key)
                ? 'bg-white/20 text-white'
                : 'bg-slate-700 text-slate-400'
            }`}>{tab.count}</span>
          </button>
        ))}
      </div>

      {/* Hata banner (eski veri varken hata alındıysa göster) */}
      {isError && servers.length > 0 && (
        <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-2.5 text-sm">
          <span className="text-red-400">Yenileme hatası:</span>
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
                className="w-64 bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-2 pl-10 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <span className="absolute left-3 top-2.5 text-slate-500"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg></span>
            </div>
            {/* IP Filter */}
            <div className="relative">
              <input
                type="text"
                placeholder="IP filtre..."
                value={ipFilter}
                onChange={(e) => setIpFilter(e.target.value)}
                className="w-48 bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            {/* Show Offline Toggle */}
            <label className="flex items-center space-x-2 cursor-pointer">
              <input
                type="checkbox"
                checked={showOffline}
                onChange={(e) => setShowOffline(e.target.checked)}
                className="w-4 h-4 text-blue-600 bg-white/[0.07] border-slate-600 rounded focus:ring-blue-500"
              />
              <span className="text-sm text-slate-300">Çevrimdışıları Göster</span>
            </label>
            {/* Status Filter */}
            {showOffline && (
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
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
              className="bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">Tümü</option>
              <option value="true">AI Ready</option>
              <option value="false">AI Ready Değil</option>
            </select>
            {/* Type Filter */}
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">Tüm Tipler</option>
              <option value="VIRTUAL">Virtual</option>
              <option value="PHYSICAL">Physical</option>
            </select>
            {/* OS Filter */}
            <select
              value={osFilter}
              onChange={(e) => setOsFilter(e.target.value)}
              className="bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">Tüm OS</option>
              <option value="linux">Linux</option>
              <option value="other">Diğer / Bilinmiyor</option>
            </select>
            {/* Node Exporter Filter */}
            <select
              value={nodeExporterFilter}
              onChange={(e) => setNodeExporterFilter(e.target.value)}
              className="bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">Node Exporter: Tümü</option>
              <option value="running">Çalışıyor</option>
              <option value="installed">Kurulu</option>
              <option value="not_installed">Kurulu Değil</option>
            </select>

          </div>
          <div className="flex items-center gap-2">
            <ActionsDropdown servers={servers} refetch={() => { refetch(); queryClient.invalidateQueries({ queryKey: ['nodeExporterStatuses'] }) }} />
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="bg-cyber-card rounded-xl border border-white/[0.06] overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full" style={{ tableLayout: 'fixed', minWidth: colWidths.reduce((a,b) => a+b, 0) }}>
            {/* Kolon genişlikleri */}
            <colgroup>
              {colWidths.map((w, i) => <col key={i} style={{ width: w }} />)}
            </colgroup>
            <thead>
              <tr className="bg-cyber-card/80 border-b border-white/[0.06] select-none">
                {([
                  { key: 'name',   label: 'Sunucu',      sortable: true,  sortKey: 'name'   },
                  { key: 'status', label: 'Durum',       sortable: true,  sortKey: 'status' },
                  { key: 'os',     label: 'OS / Kernel', sortable: false, sortKey: ''       },
                  { key: 'cpu',    label: 'CPU / RAM',   sortable: true,  sortKey: 'cpu'    },
                  { key: 'izleme', label: 'İzleme',      sortable: true,  sortKey: 'ai'     },
                  { key: 'action', label: '',           sortable: false, sortKey: '' },
                ] as Array<{key: string; label: string; sortable: boolean; sortKey?: string}>).map((col, ci) => (
                  <th key={col.key}
                    className="relative px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wide overflow-hidden">
                    {/* Başlık + sort ikonu */}
                    <div className="flex items-center gap-1 pr-3">
                      {col.sortable ? (
                        <button
                          onClick={() => toggleSort(col.sortKey || col.key)}
                          className="flex items-center gap-1 hover:text-white transition-colors group/sort"
                        >
                          {col.label}
                          <span className={`text-[11px] ml-0.5 ${sortKey === (col.sortKey || col.key) ? 'text-blue-400' : 'text-slate-600 group-hover/sort:text-slate-400'}`}>
                            {sortKey === (col.sortKey || col.key) ? (sortDirection === 'asc' ? '↑' : '↓') : '↕'}
                          </span>
                        </button>
                      ) : (
                        <span>{col.label}</span>
                      )}
                    </div>
                    {/* Resize handle */}
                    {ci < colWidths.length - 1 && (
                      <div
                        className="absolute right-0 top-0 bottom-0 w-3 flex items-center justify-center cursor-col-resize group/rz hover:bg-blue-500/10"
                        onMouseDown={e => onResizeMouseDown(ci, e)}
                      >
                        <div className="w-0.5 h-4 bg-slate-600 group-hover/rz:bg-blue-400 transition-colors rounded-full" />
                      </div>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700">
              {sortedServers.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-slate-400">
                    <p className="font-medium">Henüz sunucu yok</p>
                    <p className="text-sm mt-1">Sunucu eklemek için Entegrasyonlar modülünü kullanın (UCMDB import, hypervisor sync veya manuel host ekleme).</p>
                    <p className="text-xs mt-2 text-slate-500">API: {API_BASE_URL}</p>
                  </td>
                </tr>
              ) : sortedServers.map((server) => (
                <React.Fragment key={server.id}>
                <tr className="hover:bg-white/[0.02] transition-colors cursor-pointer border-b border-white/[0.06]/50 group" onClick={() => setSelectedServer(server)}>

                  {/* ── Sunucu Adı + IP + Hostname ── */}
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 text-lg ${
                        server.status === 'ONLINE'
                          ? 'bg-green-500/20 ring-1 ring-green-500/40'
                          : server.status === 'OFFLINE'
                          ? 'bg-white/[0.07]/50 ring-1 ring-slate-600/40'
                          : 'bg-yellow-500/20 ring-1 ring-yellow-500/40'
                      }`}>
                        <span className="text-[10px] font-bold text-slate-400">{server.server_type === 'PHYSICAL' ? 'PHY' : 'VM'}</span>
                      </div>
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-white group-hover:text-blue-300 transition-colors truncate max-w-[180px]">
                          {server.name}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                          <span className="text-xs font-mono text-slate-400">{server.ip_address || '-'}</span>
                          {server.hypervisor_name ? (
                            <span className="inline-flex items-center gap-0.5 text-[11px] text-slate-500 bg-white/[0.07]/50 px-1.5 py-0.5 rounded">
                              ☁ {server.hypervisor_name}
                            </span>
                          ) : server.hostname && server.hostname !== server.name && server.hostname !== server.ip_address ? (
                            <span className="text-xs text-slate-600 truncate max-w-[100px]">{server.hostname}</span>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  </td>

                  {/* ── Durum ── */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    {server.status === 'ONLINE' ? (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-green-500/15 text-green-400 border border-green-500/30">
                        <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
                        Aktif
                      </span>
                    ) : server.status === 'OFFLINE' ? (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-white/[0.07]/50 text-slate-400 border border-slate-600/50">
                        <span className="w-1.5 h-1.5 bg-slate-500 rounded-full" />
                        Çevrimdışı
                      </span>
                    ) : (
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${getStatusBadge(server.status)}`}>
                        <span className="w-1.5 h-1.5 rounded-full bg-current" />
                        {server.status}
                      </span>
                    )}
                  </td>

                  {/* ── OS / Kernel ── */}
                  <td className="px-4 py-3">
                    {(() => {
                      const osTypeLower = (server.os_type || '').toLowerCase()
                      const osReleaseLower = (server.os_release_id || '').toLowerCase()
                      const osVersionLower = (server.os_version || '').toLowerCase()
                      const isWindows = osTypeLower.includes('windows') || osReleaseLower.includes('windows') || osVersionLower.includes('windows')
                      const icon = isWindows ? 'WIN' :
                                   server.os_release_id === 'rhel'   ? 'RH' :
                                   server.os_release_id === 'ol'     ? 'OE' :
                                   server.os_release_id === 'rocky'  ? 'RK' :
                                   server.os_release_id === 'ubuntu' ? 'UB' :
                                   server.os_release_id === 'debian' ? 'DEB' :
                                   osVersionLower.includes('red hat') ? 'RH' :
                                   osVersionLower.includes('oracle')  ? 'OE' :
                                   osVersionLower.includes('rocky')   ? 'RK' :
                                   osVersionLower.includes('ubuntu')  ? 'UB' :
                                   osVersionLower.includes('suse') || osTypeLower.includes('sles') ? 'SUSE' :
                                   osTypeLower.includes('linux') || osReleaseLower ? 'LNX' : '?'
                      const iconColor = isWindows ? 'text-blue-400' : icon === '?' ? 'text-slate-600' : 'text-green-400'
                      const osName = isWindows
                        ? (server.os_type || server.os_version || 'Windows')
                        : server.os_release_id
                          ? `${server.os_release_id.toUpperCase()} ${server.os_version_id || ''}`
                          : server.os_version?.replace('(Plow)','').replace('(Ootpa)','').trim() || server.os_type || null
                      return (
                        <div className="flex items-start gap-2">
                          <span className={`text-[10px] font-bold mt-0.5 flex-shrink-0 bg-slate-700/60 px-1.5 py-0.5 rounded ${iconColor}`}>{icon}</span>
                          <div className="min-w-0">
                            {osName ? (
                              <div className="text-sm font-medium text-white truncate max-w-[180px]" title={osName}>
                                {osName}
                              </div>
                            ) : (
                              <div className="text-xs text-slate-600 italic">Bilinmiyor</div>
                            )}
                            {server.kernel_version && (
                              <div className="text-[11px] text-slate-500 font-mono truncate max-w-[200px] mt-0.5"
                                   title={server.kernel_version}>
                                {server.kernel_version}
                              </div>
                            )}
                          </div>
                        </div>
                      )
                    })()}
                  </td>

                  {/* ── CPU / RAM ── */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="space-y-1">
                      {server.cpu_cores > 0 ? (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-slate-400 w-7">CPU</span>
                          <span className="text-sm font-medium text-white">{server.cpu_cores}</span>
                          <span className="text-xs text-slate-500">çekirdek</span>
                        </div>
                      ) : (
                        <div className="text-xs text-slate-600">—</div>
                      )}
                      {server.memory_gb > 0 && (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-slate-400 w-7">RAM</span>
                          <span className="text-sm font-medium text-white">{server.memory_gb}</span>
                          <span className="text-xs text-slate-500">GB</span>
                        </div>
                      )}
                    </div>
                  </td>

                  {/* ── İzleme (AI + Metrik) ── */}
                  <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                    <div className="flex flex-wrap gap-1.5">
                      {server.ai_ready && server.status === 'ONLINE' && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-blue-500/15 text-blue-300 border border-blue-500/25">
                          AI
                        </span>
                      )}
                      {server.node_exporter?.running || server.node_exporter?.installed ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-green-500/15 text-green-400 border border-green-500/25">
                          <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
                          Metrik
                        </span>
                      ) : (
                        <span className="text-xs text-slate-600 italic">—</span>
                      )}
                    </div>
                  </td>

                  {/* ── İşlemler ── */}
                  <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-1">
                      {server.status === 'ONLINE' && server.ip_address && (
                        <button
                          onClick={() => {
                            // Yeni popup pencerede aç
                            const w = window.open(
                              `/terminal/${server.id}?name=${encodeURIComponent(server.name)}&ip=${encodeURIComponent(server.ip_address)}`,
                              `ssh-${server.id}`,
                              'width=1200,height=700,resizable=yes,scrollbars=no,menubar=no,toolbar=no,location=no,status=no'
                            )
                            if (!w) {
                              // Popup engellenirse modal aç
                              setSshTarget({id: server.id, name: server.name, ip: server.ip_address})
                            }
                          }}
                          className="px-2.5 py-1.5 text-xs bg-green-700/40 hover:bg-green-700 text-green-300 rounded-lg transition-colors font-mono"
                          title="SSH Terminal Aç (Yeni Pencere)"
                        >
                          SSH
                        </button>
                      )}
                      <button
                        onClick={() => setSelectedServer(server)}
                        className="px-2.5 py-1.5 text-xs bg-white/[0.07] hover:bg-slate-600 text-slate-200 rounded-lg transition-colors"
                        title="Detay"
                      >
                        Detay
                      </button>
                      <button
                        onClick={async () => {
                          if (await showConfirm('Bu sunucuyu silmek istediğinize emin misiniz?')) {
                            deleteMutation.mutate(server.id)
                          }
                        }}
                        className="px-2.5 py-1.5 text-xs text-red-400 hover:text-white hover:bg-red-700 rounded-lg transition-colors"
                        title="Sil"
                      >
                        Sil
                      </button>
                    </div>
                  </td>
                </tr>
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {sortedServers.length === 0 && (
          <div className="text-center py-12 text-slate-500">
            {searchTerm || ipFilter || statusFilter !== 'all' || aiReadyFilter !== 'all' || typeFilter !== 'all' || nodeExporterFilter !== 'all'
              ? 'Filtreye uygun sunucu bulunamadı' 
              : 'Henüz sunucu yok — envanter Entegrasyonlar üzerinden eklenir'}
          </div>
        )}
      </div>

    </div>

      {selectedServer && (
        <ServerDetailDrawer server={selectedServer} onClose={() => setSelectedServer(null)} />
      )}

      {/* SSH Terminal Modal */}
      {sshTarget && (
        <Suspense fallback={
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80">
            <div className="w-10 h-10 border-2 border-green-500 border-t-transparent rounded-full animate-spin" />
          </div>
        }>
          <SshTerminalModal
            serverId={sshTarget.id}
            serverName={sshTarget.name}
            serverIp={sshTarget.ip}
            onClose={() => setSshTarget(null)}
          />
        </Suspense>
      )}
    </>
  )
}

export default Servers

