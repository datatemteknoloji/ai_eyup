import React, { useState, useEffect, useRef, Suspense } from 'react'
import {
  ChevronDown, Settings2, Activity, Wifi,
  RefreshCw, CheckCircle2, AlertCircle, AlertTriangle,
  Cloud, Camera, Tag, Radio,
  Terminal, Info, Trash2, ShieldCheck, HardDrive,
} from 'lucide-react'
import { lazyWithRetry } from '../lib/lazyWithRetry'
const SshTerminalModal = lazyWithRetry(() => import('../components/SshTerminal'))
import BulkJobOverlay, { persistBulkJobId, restoreActiveBulkJobId, beginBulkJobModal } from '../components/BulkJobOverlay'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import { fetchServersPage } from '../api/servers'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { isPoweredOn } from '../utils/powerState'
import { OsIcon } from '../components/OsIcon'
import { shortenOsLabel, fullOsLabel, serverTypeLabel } from '../lib/osLabel'
import { useAuth } from '../auth/AuthContext'
import { useT, useLocale } from '../i18n/LocaleProvider'
import type { TranslationKey } from '../i18n/messages'

// ─── Shared Confirm Modal ──────────────────────────────────────────────────────
const ConfirmModal = ({ message, onConfirm, onCancel }: {
  message: string; onConfirm: () => void; onCancel: () => void
}) => {
  const t = useT()
  return (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
    <div className="bg-cyber-card border border-slate-600 rounded-2xl shadow-2xl p-6 max-w-sm w-full mx-4">
      <div className="flex items-start gap-3 mb-5">
        <div className="w-9 h-9 rounded-full bg-yellow-500/15 border border-yellow-500/30 flex items-center justify-center flex-shrink-0 mt-0.5">
          <AlertTriangle size={16} strokeWidth={2} className="text-yellow-400" />
        </div>
        <div>
          <div className="text-sm font-semibold text-white mb-1">{t('confirm_title')}</div>
          <div className="text-sm text-slate-300 leading-relaxed">{message}</div>
        </div>
      </div>
      <div className="flex gap-3 justify-end">
        <button onClick={onCancel} className="px-4 py-2 rounded-lg text-sm text-slate-300 hover:text-white bg-white/[0.07] hover:bg-slate-600 border border-slate-600 transition-colors">{t('cancel')}</button>
        <button onClick={onConfirm} className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-red-600 hover:bg-red-500 border border-red-500/50 transition-colors">{t('confirm_ok')}</button>
      </div>
    </div>
  </div>
  )
}

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
  vm_guest_os_full?: string
  vm_name?: string
  vm_guest_hostname?: string
  kernel_version: string
  server_type: string
  cpu_cores: number
  memory_gb: number
  ai_ready: boolean
  has_ssh_secret?: boolean
  ssh_username?: string
  hypervisor_id: number | null
  hypervisor_name: string | null
  vcenter_name?: string | null
  vcenter_endpoint?: string | null
  vm_host_name?: string | null
  vm_host_ref?: string | null
  connection_config: any
  node_exporter?: {
    installed: boolean
    running: boolean
  }
}

/** OS kimliği — liste birincil etiketi. */
function displayHostname(s: Pick<Server, 'hostname' | 'vm_guest_hostname' | 'name'>): string {
  return (s.hostname || s.vm_guest_hostname || s.name || '').trim() || '-'
}

function _normNameToken(v: string): string {
  return v.trim().toLowerCase().replace(/[^a-z0-9]/g, '')
}

/** VM adı hostname'den farklıysa ikincil satırda göster. */
function displayVmLabel(s: Server): string | null {
  const vm = (s.vm_name || s.name || '').trim()
  if (!vm) return null
  const hn = displayHostname(s)
  if (_normNameToken(vm) === _normNameToken(hn)) return null
  if (_normNameToken(vm.split('.')[0] || '') === _normNameToken(hn.split('.')[0] || '')) return null
  return vm
}

/** vm_name dolu ve normalize(short hostname) ≠ normalize(vm_name). */
function hasNameMismatch(s: Server): boolean {
  const vm = (s.vm_name || '').trim()
  if (!vm) return false
  const hn = (s.hostname || '').trim()
  if (!hn) return true
  const shortHn = hn.split('.')[0] || hn
  return _normNameToken(shortHn) !== _normNameToken(vm)
}

// ─── AI Ready Güncelle Butonu ─────────────────────────────────────────────────
const AiReadyUpdateButton: React.FC<{
  onDone: () => void
  onJobStart?: (jobId: string) => void
  asMenuItem?: boolean
  selectedIds?: number[]
  sshOpsEnabled?: boolean
}> = ({ onDone, onJobStart, asMenuItem, selectedIds = [], sshOpsEnabled = true }) => {
  const t = useT()
  const [loading, setLoading] = React.useState(false)
  const [result, setResult]   = React.useState<string | null>(null)
  const [confirmState, setConfirmState] = React.useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const showConfirm = (msg: string): Promise<boolean> => new Promise(resolve => setConfirmState({ msg, resolve }))

  const handleClick = async () => {
    if (!sshOpsEnabled) {
      alert(t('ssh_cred_hint'))
      return
    }
    const count = selectedIds.length
    const scope = count > 0 ? t('scope_selected_linux', { n: count }) : t('scope_all_linux')
    if (!await showConfirm(t('ai_ready_confirm', { scope }))) return

    setLoading(true); setResult(null)
    try {
      const body = count > 0 ? JSON.stringify({ server_ids: selectedIds }) : undefined
      const r = await fetch(`${API_BASE_URL}/servers/update-ai-ready`, {
        method: 'POST',
        ...(body ? { headers: { 'Content-Type': 'application/json' }, body } : {}),
      })
      const text = await r.text()
      let d: any = null
      try { d = text ? JSON.parse(text) : null } catch {
        setResult(r.status === 504 || r.status === 502 ? t('timeout_bg') : `HTTP ${r.status}`)
        return
      }
      if (r.ok) {
        if (d.job_id && onJobStart) {
          onJobStart(d.job_id)
        } else {
          setResult(d.message || t('queued_n', { n: d.tested ?? 0 }))
          onDone()
          setTimeout(() => { setResult(null); onDone() }, 8000)
        }
      } else {
        setResult(typeof d?.detail === 'string' ? d.detail : t('error_generic'))
      }
    } finally { setLoading(false) }
  }

  return (
    <>
      {confirmState && <ConfirmModal message={confirmState.msg} onConfirm={() => { confirmState.resolve(true); setConfirmState(null) }} onCancel={() => { confirmState.resolve(false); setConfirmState(null) }} />}
      <button
        onClick={handleClick}
        disabled={loading || !sshOpsEnabled}
        className={asMenuItem
          ? "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-slate-300 hover:bg-slate-700 hover:text-white transition-colors disabled:opacity-50 text-left"
          : "inline-flex items-center gap-2 px-3 py-2 bg-white/[0.07] border border-slate-600 text-slate-200 rounded-lg hover:bg-slate-600 hover:border-slate-500 transition-all disabled:opacity-50 text-sm"}
        title={sshOpsEnabled ? t('ai_ready_update_title') : t('ssh_cred_hint')}
      >
        {loading ? (
          <>
            <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin flex-shrink-0" />
            <span>{t('starting')}</span>
          </>
        ) : result ? (
          <>
            <CheckCircle2 size={15} className="text-green-400 flex-shrink-0" />
            <span className="truncate text-xs">{result}</span>
          </>
        ) : (
          <>
            <Wifi size={15} className="flex-shrink-0 text-slate-400" />
            <span>{t('ai_ready_update')}</span>
          </>
        )}
      </button>
    </>
  )
}

// ─── OS Bilgisi Yenile Butonu ──────────────────────────────────────────────────
const OsRefreshButton: React.FC<{
  onDone: () => void
  onJobStart?: (jobId: string) => void
  asMenuItem?: boolean
  selectedIds?: number[]
  sshOpsEnabled?: boolean
}> = ({ onDone, onJobStart, asMenuItem, selectedIds = [], sshOpsEnabled = true }) => {
  const t = useT()
  const [loading, setLoading] = React.useState(false)
  const [result, setResult]   = React.useState<string | null>(null)
  const [confirmState, setConfirmState] = React.useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const showConfirm = (msg: string): Promise<boolean> => new Promise(resolve => setConfirmState({ msg, resolve }))

  const handleClick = async () => {
    if (!sshOpsEnabled) {
      alert(t('ssh_cred_hint'))
      return
    }
    const ids = selectedIds.length > 0 ? selectedIds : undefined

    const confirmed = await showConfirm(
      ids ? t('os_refresh_confirm_sel', { n: ids.length }) : t('os_refresh_confirm_all')
    )
    if (!confirmed) return

    setLoading(true); setResult(null)
    try {
      const r = await fetch('/api/v1/servers/refresh-os-info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: ids ? JSON.stringify({ server_ids: ids }) : '{}',
      })
      const text = await r.text()
      let d: any = null
      try { d = text ? JSON.parse(text) : null } catch {
        setResult(r.status === 504 || r.status === 502 ? t('timeout') : `HTTP ${r.status}`)
        return
      }
      if (r.ok) {
        if (d.job_id && onJobStart) {
          onJobStart(d.job_id)
        } else {
          setResult(d.message || t('queued_n', { n: d.updated ?? 0 }))
          onDone()
          setTimeout(() => { setResult(null); onDone() }, 8000)
        }
      } else {
        setResult(typeof d?.detail === 'string' ? d.detail : t('error_generic'))
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
        disabled={loading || !sshOpsEnabled}
        className={asMenuItem
          ? "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-slate-300 hover:bg-slate-700 hover:text-white transition-colors disabled:opacity-50 text-left"
          : "inline-flex items-center gap-2 px-3 py-2 bg-white/[0.07] border border-slate-600 text-slate-200 rounded-lg hover:bg-slate-600 hover:border-slate-500 transition-all disabled:opacity-50 text-sm"}
        title={sshOpsEnabled ? t('os_refresh_title') : t('ssh_cred_hint')}
      >
        {loading ? (
          <>
            <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin flex-shrink-0" />
            <span>{t('starting')}</span>
          </>
        ) : result ? (
          <>
            <CheckCircle2 size={15} className="text-green-400 flex-shrink-0" />
            <span className="truncate text-xs">{result}</span>
          </>
        ) : (
          <>
            <RefreshCw size={15} className="flex-shrink-0 text-slate-400" />
            <span>{t('os_refresh')}</span>
          </>
        )}
      </button>
    </>
  )
}

// ─── İşlemler Dropdown ────────────────────────────────────────────────────────
const ActionsDropdown: React.FC<{
  refetch: () => void
  selectedIds: number[]
  bulkJobId: string | null
  setBulkJobId: (id: string | null) => void
  sshOpsEnabled: boolean
}> = ({ refetch, selectedIds, bulkJobId, setBulkJobId, sshOpsEnabled }) => {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [checkLoading, setCheckLoading] = useState(false)
  const [checkResult, setCheckResult] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const startJob = (jobId: string) => {
    beginBulkJobModal(jobId)
    setBulkJobId(jobId)
    setOpen(false)
  }

  const handleCheckHealth = async () => {
    setCheckLoading(true); setCheckResult(null)
    try {
      const body = selectedIds.length > 0 ? JSON.stringify({ server_ids: selectedIds }) : undefined
      const r = await fetch(`${API_BASE_URL}/servers/check-health`, {
        method: 'POST',
        ...(body ? { headers: { 'Content-Type': 'application/json' }, body } : {}),
      })
      const d = await r.json()
      if (r.ok) {
        if (d.job_id) {
          startJob(d.job_id)
        } else {
          setCheckResult(t('check_stats', { checked: d.stats?.checked || 0, updated: d.stats?.updated || 0 }))
          refetch()
          setTimeout(() => setCheckResult(null), 5000)
        }
      } else {
        setCheckResult(t('error_generic') + ': ' + (d.detail || '?'))
      }
    } catch { setCheckResult(t('conn_error')) }
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
        <span>{t('actions')}</span>
        <ChevronDown size={13} className={`transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 bg-slate-800 border border-slate-700/80 rounded-xl shadow-2xl shadow-black/40 z-50 w-56 p-1.5 flex flex-col gap-0.5">
          <p className="text-[10px] text-slate-500 px-3 pt-1 pb-0.5 uppercase tracking-wider font-medium">{t('bulk_actions')}</p>

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
            <span className="truncate">{checkResult ?? (checkLoading ? t('starting') : t('check_health'))}</span>
          </button>

          <AiReadyUpdateButton onDone={refetch} onJobStart={startJob} asMenuItem selectedIds={selectedIds} sshOpsEnabled={sshOpsEnabled} />

          <div className="h-px bg-slate-700/60 mx-2 my-0.5" />

          <OsRefreshButton onDone={refetch} onJobStart={startJob} asMenuItem selectedIds={selectedIds} sshOpsEnabled={sshOpsEnabled} />
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

function fmtUptime(seconds: number | null, t: (key: TranslationKey, vars?: Record<string, string | number>) => string): string {
  if (!seconds) return '-'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return t('uptime_dh', { d, h })
  if (h > 0) return t('uptime_hm', { h, m })
  return t('uptime_m', { m })
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
// Renk kodlaması zaten TIER_COLORS'taki bg/text/border ile sağlanıyor —
// eskiden ek olarak duran 🔴/🟡/🟢/⚪ emoji önekleri kaldırıldı (DESIGN.md: "Emoji kullanılmaz").
function TierBadge({ tier }: { tier: string }) {
  const t = useT()
  const labels: Record<string, string> = {
    production: 'Production',
    staging: 'Staging',
    development: 'Development',
    unknown: t('tier_unknown'),
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-md border font-medium ${TIER_COLORS[tier] || TIER_COLORS['unknown']}`}>
      {labels[tier] || tier}
    </span>
  )
}

export function ServerDetailDrawer({ server, onClose }: { server: Server; onClose: () => void }) {
  const t = useT()
  const { locale } = useLocale()
  const dateLoc = locale === 'en' ? 'en-GB' : 'tr-TR'
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

  const { data: vmDetails, refetch: refetchVmDetails, isFetching: vmDetailsFetching } = useQuery<{
    hypervisor_vm_id?: string
    hypervisor_name?: string
    vcenter_name?: string
    vcenter_endpoint?: string
    vm_host_name?: string
    vm_host_ref?: string
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
    source?: string
    live_error?: string | null
  }>({
    queryKey: ['server-vm-details', server.id],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/snapshots/server/${server.id}/vm-details?live=true`)
      if (!r.ok) return { can_snapshot: false }
      return r.json()
    },
    enabled: tab === 'info' && !!server.hypervisor_id,
    refetchInterval: false,
    staleTime: 30_000,
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
      if (e?.name !== 'AbortError') setAnalyzeText(t('analyze_failed_md'))
    } finally { setIsAnalyzing(false) }
  }

  const sshUser =
    server.ssh_username
    || server.connection_config?.username
    || ''
  const vcenterLabel = server.vcenter_name || server.hypervisor_name || ''
  const vcenterEndpoint = server.vcenter_endpoint || ''
  const esxiHost =
    vmDetails?.vm_host_name
    || server.vm_host_name
    || ''
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
            <h2 className="text-white font-semibold text-base truncate" title={server.name !== displayHostname(server) ? server.name : undefined}>
              {displayHostname(server)}
            </h2>
            <div className="flex items-center gap-2 mt-0.5 flex-wrap">
              <p className="text-slate-400 text-xs font-mono">{server.ip_address}</p>
              {vcenterLabel && (
                <span
                  className="inline-flex items-center gap-1 text-xs text-slate-500 bg-white/[0.07]/50 px-1.5 py-0.5 rounded"
                  title={vcenterEndpoint ? `vCenter: ${vcenterLabel} (${vcenterEndpoint})` : `vCenter: ${vcenterLabel}`}
                >
                  <Cloud size={11} strokeWidth={2} /> {vcenterLabel}
                </span>
              )}
              {esxiHost && (
                <span
                  className="inline-flex items-center gap-1 text-xs text-slate-500 bg-white/[0.07]/50 px-1.5 py-0.5 rounded"
                  title={`ESXi host: ${esxiHost}`}
                >
                  ESXi {esxiHost}
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
                if (!w) alert(t('popup_blocked'))
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
          {([['info', t('tab_info')], ['perf', t('tab_perf')], ['events', t('tab_events')]] as const).map(([id, label]) => (
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
                  [t('label_server_name'), server.name],
                  [t('label_ip'), server.ip_address || '-'],
                  ['Hostname', server.hostname || '-'],
                  ...(vcenterLabel ? [[
                    'vCenter',
                    vcenterEndpoint ? `${vcenterLabel} (${vcenterEndpoint})` : vcenterLabel,
                  ]] : []),
                  ...(esxiHost ? [['ESXi host', esxiHost]] : []),
                  [t('label_type'), server.server_type || '-'],
                  [t('label_os_distro'), server.os_release_id ? server.os_release_id.toUpperCase() : (server.os_type || '-')],
                  [t('label_os_version'), server.os_version_id ? `${server.os_version_id} — ${server.os_version || ''}` : (server.os_version || '-')],
                  ['Kernel', server.kernel_version || '-'],
                  ['CPU', server.cpu_cores ? t('n_cores', { n: server.cpu_cores }) : '-'],
                  [t('memory'), server.memory_gb ? `${server.memory_gb} GB` : '-'],
                  [t('label_ssh_user'), sshUser || '-'],
                  [t('ai_ready'), '__AI_READY_TOGGLE__'],
                  [t('label_tier'), '__TIER_SELECT__'],
                  ['Node Exporter', server.node_exporter?.running ? t('node_exporter_running') : server.node_exporter?.installed ? t('ne_installed_stopped') : t('node_exporter_missing')],
                ].map(([label, value]) => (
                  <div key={label} className="bg-cyber-card/50 rounded-lg p-3 border border-white/[0.06]/50">
                    <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-0.5">{label}</p>
                    {value === '__AI_READY_TOGGLE__' ? (
                      <div className="flex items-center justify-between mt-0.5">
                        <span className={`text-sm font-medium ${server.ai_ready ? 'text-green-400' : 'text-slate-400'}`}>
                          {server.ai_ready ? t('ai_ready') : t('ai_ready_not')}
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
                          {server.ai_ready ? t('ai_ready_remove') : t('ai_ready_add')}
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
                          <option value="unknown">{t('tier_unknown')}</option>
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
                    <h3 className="text-sm font-medium text-white">{t('update_history')}</h3>
                    {updateHistory.pending_reboot && (
                      <span className="text-xs bg-yellow-500/20 text-yellow-300 border border-yellow-500/30 px-2 py-0.5 rounded-full animate-pulse">
                        {t('reboot_needed')}
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
                        {t('packages_n', { n: h.packages_updated })}
                      </span>
                      {h.reboot_required && !h.rebooted && (
                        <span className="text-yellow-400 flex-shrink-0 font-bold">!</span>
                      )}
                      <span className="text-slate-500 flex-shrink-0">
                        {h.completed_at ? new Date(h.completed_at).toLocaleDateString(dateLoc) : '—'}
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
                      {t('vm_details')}
                      {vmDetails?.vm_last_sync && (
                        <span className="text-[10px] text-slate-500 font-normal">
                          {t('last_sync')}: {new Date(vmDetails.vm_last_sync).toLocaleString(dateLoc)}
                          {vmDetails.source === 'vcenter_live' ? ' · live' : ''}
                          {vmDetailsFetching ? ' · …' : ''}
                        </span>
                      )}
                    </h3>
                    {/* Manuel yenileme — canlı vCenter API */}
                    <button
                      onClick={handleSearchVm}
                      disabled={vmSearching || vmDetailsFetching}
                      className="flex items-center gap-1 px-2.5 py-1 text-xs rounded border border-slate-600/50 bg-white/[0.04] text-slate-400 hover:text-slate-200 hover:bg-white/[0.05] transition-colors disabled:opacity-50"
                      title={t('refresh_vm_title')}
                    >
                      {(vmSearching || vmDetailsFetching)
                        ? <><span className="w-2.5 h-2.5 border border-current border-t-transparent rounded-full animate-spin" /> {t('refreshing')}</>
                        : `↻ ${t('refresh_action')}`
                      }
                    </button>
                  </div>
                  {vmDetails?.live_error && (
                    <p className="text-[11px] text-amber-400/90">{vmDetails.live_error}</p>
                  )}

                  {/* VM detay grid */}
                  {vmDetails?.hypervisor_vm_id ? (
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                      {[
                        { label: 'VM ID',              val: vmDetails.hypervisor_vm_id },
                        { label: t('label_vm_name'),   val: vmDetails.vm_name },
                        {
                          label: 'vCenter',
                          val: (vmDetails.vcenter_name || vmDetails.hypervisor_name)
                            ? (
                                vmDetails.vcenter_endpoint
                                  ? `${vmDetails.vcenter_name || vmDetails.hypervisor_name} (${vmDetails.vcenter_endpoint})`
                                  : (vmDetails.vcenter_name || vmDetails.hypervisor_name)
                              )
                            : undefined,
                        },
                        { label: 'ESXi host',          val: vmDetails.vm_host_name },
                        { label: 'Guest Host',         val: vmDetails.vm_guest_hostname },
                        { label: 'Guest IP',           val: vmDetails.vm_guest_ip },
                        { label: 'vCPU',               val: vmDetails.vm_cpu_count != null ? `${vmDetails.vm_cpu_count} core` : undefined },
                        { label: t('memory'),           val: vmDetails.vm_memory_mb != null ? `${(vmDetails.vm_memory_mb / 1024).toFixed(1)} GB` : undefined },
                        { label: 'Disk',               val: vmDetails.vm_disk_gb != null ? `${vmDetails.vm_disk_gb} GB` : undefined },
                        { label: 'Cluster',            val: vmDetails.vm_cluster },
                        { label: 'Datastore',          val: vmDetails.vm_datastore },
                        { label: t('hw_version'),      val: vmDetails.vm_hardware_version },
                      ].map(({ label, val }) => val ? (
                        <div key={label} className="flex gap-1.5">
                          <span className="text-slate-500 flex-shrink-0 w-24">{label}</span>
                          <span className="text-slate-200 truncate font-mono text-[11px]">{val}</span>
                        </div>
                      ) : null)}

                      {/* Güç durumu */}
                      {vmDetails.vm_power_state && (
                        <div className="flex gap-1.5 col-span-2">
                          <span className="text-slate-500 w-24 flex-shrink-0">{t('power_state')}</span>
                          <span className={`font-medium ${
                            isPoweredOn(vmDetails.vm_power_state) ? 'text-green-400' : 'text-red-400'
                          }`}>
                            {vmDetails.vm_power_state}
                          </span>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500 italic">
                      {t('vm_id_not_saved')}
                    </p>
                  )}

                  {/* Ağ adaptörleri */}
                  {(vmDetails?.vm_network_info?.length ?? 0) > 0 && (
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">{t('network_adapters')}</p>
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
                      <h3 className="flex items-center gap-1.5 text-sm font-medium text-white">
                        <Camera size={14} strokeWidth={1.8} /> VM Snapshot
                      </h3>
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
                          <option value="1d">{t('retention_1d')}</option>
                          <option value="1w">{t('retention_1w')}</option>
                          <option value="1m">{t('retention_1m')}</option>
                          <option value="indefinite">{t('retention_indefinite')}</option>
                        </select>
                      )}
                      {/* Snapshot Al butonu — VM ID yoksa backend otomatik arar */}
                      {server.hypervisor_id && (
                        <button
                          disabled={snapCreating}
                          title={t('snapshot_take_title')}
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
                                alert(data.detail || t('snapshot_start_failed'))
                              }
                            } finally {
                              // Buton 3sn sonra tekrar aktif olsun
                              setTimeout(() => setSnapCreating(false), 3000)
                            }
                          }}
                          className="flex items-center gap-1 px-3 py-1 text-xs rounded border transition-colors disabled:opacity-50 bg-cyan-700/40 text-cyan-300 border-cyan-500/30 hover:bg-cyan-700/50"
                        >
                          {snapCreating
                            ? <><span className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" /> {t('starting')}</>
                            : t('snapshot_take')
                          }
                        </button>
                      )}
                    </div>
                  </div>

                  {/* VM ID yok uyarısı */}
                  {vmSnapshots?.vm_id_missing && !snapCreating && (
                    <div className="flex items-start gap-2 text-xs text-yellow-400/80 bg-yellow-500/5 border border-yellow-500/20 rounded-lg px-3 py-2">
                      <AlertTriangle size={12} strokeWidth={2} className="flex-shrink-0 mt-0.5" />
                      <span>{t('vm_id_unknown_hint')}</span>
                    </div>
                  )}

                  {/* Hypervisor bağlı değil */}
                  {!vmSnapshots?.hypervisor_connected && (
                    <p className="text-xs text-slate-500">{t('physical_no_snapshot')}</p>
                  )}

                  {/* Uygulama tarafından takip edilen snapshotlar */}
                  {(vmSnapshots?.tracked?.length ?? 0) > 0 && (
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-1.5">{t('tracked_snapshots')}</p>
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
                                {s.status === 'pending' && <span className="text-yellow-400">{t('creating_on_vcenter')}</span>}
                                {s.status === 'failed' && <span className="text-red-400">{t('failed')}</span>}
                                <span>{s.retention} · {new Date(s.created_at).toLocaleString(dateLoc)}</span>
                                {s.expires_at && <span>· {t('expires_on', { date: new Date(s.expires_at).toLocaleDateString(dateLoc) })}</span>}
                              </div>
                            </div>
                            {s.status !== 'pending' && (
                              <button
                                onClick={async () => {
                                  if (!await showConfirm(t('snapshot_delete_confirm'))) return
                                  const r = await fetch(`${API_BASE_URL}/snapshots/${s.id}`, { method: 'DELETE' })
                                  if (r.ok) refetchSnapshots()
                                  else { const e = await r.json().catch(() => ({})); alert(e.detail || t('delete_failed')) }
                                }}
                                className="text-red-400 hover:text-red-300 px-2 py-0.5 rounded hover:bg-red-500/10 flex-shrink-0"
                                title={t('snapshot_delete_title')}
                              >
                                {t('delete')}
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
                      <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-1.5">{t('all_hv_snapshots')}</p>
                      <div className="space-y-1.5 max-h-40 overflow-y-auto">
                        {vmSnapshots!.external.map((s, i) => (
                          <div key={s.id || i} className="flex items-center gap-2 text-xs bg-white/[0.02] rounded-lg px-3 py-2 border border-white/[0.04]">
                            <Tag size={12} strokeWidth={2} className="text-slate-400 flex-shrink-0" />
                            <div className="flex-1 min-w-0">
                              <div className="text-slate-300 truncate">{s.name}</div>
                              {s.description && <div className="text-slate-500 text-[10px] truncate">{s.description}</div>}
                              {s.created && <div className="text-slate-500 text-[10px]">{new Date(s.created).toLocaleString(dateLoc)}</div>}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Hiç snapshot yok */}
                  {(vmSnapshots?.tracked?.length ?? 0) === 0 && (vmSnapshots?.external?.length ?? 0) === 0 && vmSnapshots?.hypervisor_connected && (
                    <p className="text-xs text-slate-500">{t('no_snapshots')}</p>
                  )}
                </div>
              )}

              {/* AI Analiz */}
              <div className="bg-cyber-card/50 rounded-xl border border-white/[0.06] p-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-medium text-white">{t('ai_analysis')}</h3>
                  <button onClick={startAnalyze} disabled={isAnalyzing}
                    className="px-3 py-1 text-xs bg-blue-600/30 text-blue-300 border border-blue-500/30 rounded hover:bg-blue-600/40 disabled:opacity-50">
                    {isAnalyzing ? t('analyzing') : analyzeText ? t('analyze_again') : t('analyze')}
                  </button>
                </div>
                {analyzeText ? (
                  <div className="chat-response-content prose prose-invert prose-sm max-w-none text-slate-200 text-xs">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{analyzeText}</ReactMarkdown>
                    {isAnalyzing && <span className="inline-block w-1.5 h-3 bg-blue-400 animate-pulse ml-0.5 rounded-sm" />}
                  </div>
                ) : isAnalyzing ? (
                  <div className="flex items-center gap-2 text-slate-400 text-xs">
                    <div className="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                    <span>{t('ai_analyzing')}</span>
                  </div>
                ) : (
                  <p className="text-slate-500 text-xs">{t('ai_analyze_hint')}</p>
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
                  <span>{t('lm_loading')}</span>
                </div>
              ) : (!metrics?.has_node_exporter && !metrics?.source) ? (
                <div className="text-center py-10 text-slate-500">
                  <Radio size={32} strokeWidth={1.5} className="mx-auto mb-3" />
                  <p className="text-sm">{t('ne_no_metrics')}</p>
                  {server.server_type === 'VIRTUAL' && (
                    <p className="text-xs text-slate-600 mt-1">{t('check_hypervisor')}</p>
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
                    {metrics.power_state && (() => {
                      const isOn = isPoweredOn(metrics.power_state)
                      return (
                        <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${isOn ? 'bg-green-500/20 text-green-400 border-green-500/30' : 'bg-red-500/20 text-red-400 border-red-500/30'}`}>
                          {isOn ? t('power_on') : t('power_off')}
                        </span>
                      )
                    })()}
                  </div>

                  {/* Gauge cards */}
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { label: 'CPU', value: metrics.cpu_percent, icon: '', color: 'text-yellow-400' },
                      { label: t('memory'), value: metrics.mem_percent, icon: '', color: 'text-blue-400' },
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
                    <MetricBar label={t('cpu_usage')} value={metrics.cpu_percent} colorClass={cpuColor(metrics.cpu_percent)} />
                    <MetricBar label={`${t('memory')}  ${metrics.mem_used_gb != null ? `(${metrics.mem_used_gb}/${metrics.mem_total_gb} GB)` : ''}`} value={metrics.mem_percent} colorClass={memColor(metrics.mem_percent)} />
                    <MetricBar label={`Disk  ${metrics.disk_avail_gb != null ? `(${t('disk_free_of', { avail: metrics.disk_avail_gb, total: metrics.disk_total_gb ?? '-' })})` : ''}`} value={metrics.disk_percent} colorClass={diskColor(metrics.disk_percent)} />
                  </div>

                  {/* Extra info */}
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      metrics.source === 'vcenter'
                        ? [t('vcpu_count'), metrics.cpu_num !== null ? String(metrics.cpu_num) : '-']
                        : ['Load 1m', metrics.load1 !== null ? String(metrics.load1) : '-'],
                      metrics.source === 'vcenter'
                        ? [t('ram_total'), metrics.mem_total_gb !== null ? `${metrics.mem_total_gb} GB` : '-']
                        : ['Load 5m', metrics.load5 !== null ? String(metrics.load5) : '-'],
                      ['Uptime', fmtUptime(metrics.uptime_seconds, t)],
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
                  <span>{t('events_loading')}</span>
                </div>
              ) : !eventsData?.groups?.length ? (
                <div className="text-center py-10 text-slate-500">
                  <p className="text-2xl font-bold text-green-400 mb-3">✓</p>
                  <p className="text-sm">{t('no_active_events')}</p>
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
                              {new Date(grp.latest_created_at).toLocaleString(dateLoc, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
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
  const t = useT()
  const { user, hasModule } = useAuth()
  const canSeeNameMismatch = Boolean(user?.is_admin || user?.role === 'admin' || hasModule('linux'))
  const [selectedServer, setSelectedServer] = useState<Server | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [searchTerm, setSearchTerm] = useState('')
  const [confirmState, setConfirmState] = useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const showConfirm = (msg: string): Promise<boolean> => new Promise(resolve => setConfirmState({ msg, resolve }))
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [showOffline, setShowOffline] = useState(false)
  const [aiReadyFilter, setAiReadyFilter] = useState<string>('all') // Tümü — Linux + Windows + diğer
  const [typeFilter, setTypeFilter] = useState<string>('all') // all, VIRTUAL, PHYSICAL
  const [osFilter, setOsFilter] = useState<string>('all') // all, linux, windows, other
  const [nodeExporterFilter, setNodeExporterFilter] = useState<string>('all') // all, installed, running, not_installed
  const [nameMismatchFilter, setNameMismatchFilter] = useState(false)
  const [page, setPage] = useState(1)
  const pageSize = 50
  const [bulkJobId, setBulkJobId] = useState<string | null>(null)
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; server: Server } | null>(null)

  const [sortKey, setSortKey] = useState<string>('hostname')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')
  const [sshTarget, setSshTarget] = useState<{id: number; name: string; ip: string} | null>(null)
  const rowClickTimer = useRef<number | null>(null)
  const selectAllRef = useRef<HTMLInputElement>(null)

  // Kolon genişlikleri (px): checkbox, sunucu, tip, durum, os, cpu, izleme, işlem
  const [colWidths, setColWidths] = useState<number[]>([40, 260, 90, 120, 240, 140, 180, 120])

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
    if (!contextMenu) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setContextMenu(null) }
    const onClick = () => setContextMenu(null)
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [contextMenu])

  const selectedIdList = [...selectedIds]

  const toggleSelect = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAllPage = () => {
    const pageIds = servers.map(s => s.id)
    const allSelected = pageIds.length > 0 && pageIds.every(id => selectedIds.has(id))
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (allSelected) pageIds.forEach(id => next.delete(id))
      else pageIds.forEach(id => next.add(id))
      return next
    })
  }

  const getContextOpIds = (server: Server): number[] => {
    if (selectedIds.has(server.id) && selectedIds.size > 0) return selectedIdList
    return [server.id]
  }

  const startBulkJob = (jobId: string) => {
    beginBulkJobModal(jobId)
    setBulkJobId(jobId)
    setContextMenu(null)
  }

  const runCheckHealth = async (ids?: number[]) => {
    const body = ids && ids.length > 0 ? JSON.stringify({ server_ids: ids }) : undefined
    const r = await fetch(`${API_BASE_URL}/servers/check-health`, {
      method: 'POST',
      ...(body ? { headers: { 'Content-Type': 'application/json' }, body } : {}),
    })
    const d = await r.json()
    if (r.ok && d.job_id) startBulkJob(d.job_id)
    else if (r.ok) refetch()
    else alert(typeof d?.detail === 'string' ? d.detail : t('health_failed'))
  }

  const runAiReadyUpdate = async (ids?: number[]) => {
    if (!sshOpsEnabled) {
      alert(t('ssh_cred_hint'))
      return
    }
    const count = ids?.length ?? 0
    const scope = count > 0 ? t('scope_selected_linux', { n: count }) : t('scope_all_linux')
    if (!await showConfirm(t('ai_ready_confirm', { scope }))) return
    const body = count > 0 ? JSON.stringify({ server_ids: ids }) : undefined
    const r = await fetch(`${API_BASE_URL}/servers/update-ai-ready`, {
      method: 'POST',
      ...(body ? { headers: { 'Content-Type': 'application/json' }, body } : {}),
    })
    const d = await r.json().catch(() => ({}))
    if (r.ok && d.job_id) startBulkJob(d.job_id)
    else if (r.ok) refetch()
    else alert(typeof d?.detail === 'string' ? d.detail : t('ai_ready_failed'))
  }

  const runOsRefresh = async (ids?: number[]) => {
    if (!sshOpsEnabled) {
      alert(t('ssh_cred_hint'))
      return
    }
    const msg = ids && ids.length > 0
      ? t('os_refresh_confirm_sel', { n: ids.length })
      : t('os_refresh_confirm_all')
    if (!await showConfirm(msg)) return
    const r = await fetch('/api/v1/servers/refresh-os-info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: ids && ids.length > 0 ? JSON.stringify({ server_ids: ids }) : '{}',
    })
    const d = await r.json().catch(() => ({}))
    if (r.ok && d.job_id) startBulkJob(d.job_id)
    else if (r.ok) refetch()
    else alert(typeof d?.detail === 'string' ? d.detail : t('os_refresh_failed'))
  }

  const openSsh = (server: Server) => {
    if (server.status !== 'ONLINE' || !server.ip_address) return
    const w = window.open(
      `/terminal/${server.id}?name=${encodeURIComponent(server.name)}&ip=${encodeURIComponent(server.ip_address)}`,
      `ssh-${server.id}`,
      'width=1200,height=700,resizable=yes,scrollbars=no,menubar=no,toolbar=no,location=no,status=no'
    )
    if (!w) setSshTarget({ id: server.id, name: server.name, ip: server.ip_address })
  }

  // Filtre değişince ilk sayfaya dön
  React.useEffect(() => {
    setPage(1)
  }, [searchTerm, statusFilter, showOffline, aiReadyFilter, typeFilter, osFilter, nodeExporterFilter, nameMismatchFilter])

  const { data: serversPage, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['servers', 'linux', page, pageSize, searchTerm, statusFilter, showOffline, aiReadyFilter, typeFilter, osFilter, nodeExporterFilter, nameMismatchFilter],
    queryFn: () =>
      fetchServersPage<Server>({
        platform: 'linux',
        page,
        page_size: pageSize,
        q: searchTerm || undefined,
        status: statusFilter !== 'all' ? statusFilter : undefined,
        hide_offline: !showOffline,
        ai_ready: aiReadyFilter === 'all' ? null : aiReadyFilter === 'true',
        server_type: typeFilter !== 'all' ? typeFilter : undefined,
        os: osFilter !== 'all' ? osFilter : undefined,
        node_exporter: nodeExporterFilter !== 'all' ? nodeExporterFilter : undefined,
        name_mismatch: canSeeNameMismatch && nameMismatchFilter ? true : null,
      }),
    refetchInterval: 60_000,
    placeholderData: (prev) => prev,
  })

  const { data: linuxSummary } = useQuery({
    queryKey: ['servers', 'summary', 'linux'],
    queryFn: async () => {
      const { fetchServersSummary } = await import('../api/servers')
      return fetchServersSummary('linux')
    },
    enabled: canSeeNameMismatch,
    refetchInterval: 120_000,
  })

  const { data: globalCreds } = useQuery({
    queryKey: ['settings', 'credentials'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/settings/credentials/`)
      if (!r.ok) return [] as Array<{ has_password?: boolean; has_private_key?: boolean }>
      return r.json()
    },
    staleTime: 60_000,
  })

  const servers = serversPage?.items ?? []
  const totalServers = serversPage?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(totalServers / pageSize))
  const globalSshReady = (globalCreds || []).some(c => c.has_password || c.has_private_key)
  const selectedHaveSecret = selectedIdList.some(id => servers.find(s => s.id === id)?.has_ssh_secret)
  const pageHaveSecret = servers.some(s => s.has_ssh_secret)
  const sshOpsEnabled = globalSshReady || (selectedIdList.length > 0 ? selectedHaveSecret : pageHaveSecret)
  const pageAllSelected = servers.length > 0 && servers.every(s => selectedIds.has(s.id))
  const pageSomeSelected = servers.some(s => selectedIds.has(s.id))

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = pageSomeSelected && !pageAllSelected
    }
  }, [pageSomeSelected, pageAllSelected])

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

  // Filtreler sunucu tarafında; burada yalnızca mevcut sayfayı sırala. NE = DB cache.
  // Çevrimdışıları Göster açıkken OFFLINE kayıtlar listenin üstüne çıkar.
  const sortedServers = [...servers].sort((a, b) => {
    if (showOffline) {
      const aOff = a.status === 'OFFLINE' ? 0 : 1
      const bOff = b.status === 'OFFLINE' ? 0 : 1
      if (aOff !== bOff) return aOff - bOff
    }

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
      case 'os': {
        const osOf = (s: Server) =>
          shortenOsLabel({
            os_type: s.os_type,
            os_version: s.os_version,
            os_release_id: s.os_release_id,
            os_version_id: s.os_version_id,
            os_pretty: s.os_version || s.vm_guest_os_full,
            vm_guest_os_full: s.vm_guest_os_full,
          }).toLowerCase()
        aValue = osOf(a)
        bValue = osOf(b)
        break
      }
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
      case 'hostname':
      case 'name':
      default:
        aValue = displayHostname(a).toLowerCase()
        bValue = displayHostname(b).toLowerCase()
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
        <p className="text-slate-400">{t('servers_loading')}</p>
      </div>
    )
  }

  if (isError && servers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4 p-6">
        <p className="text-red-400 font-medium">{t('servers_load_failed')}</p>
        <p className="text-slate-400 text-sm text-center max-w-md">
          {error instanceof Error ? error.message : t('servers_backend_hint', { url: API_BASE_URL })}
        </p>
        <button
          onClick={() => refetch()}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg"
        >
          {t('retry')}
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
          { key: 'all', label: t('filter_all'), count: platformCounts.all },
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
          <span className="text-red-400">{t('refresh_error')}</span>
          <span className="text-red-300">{error instanceof Error ? error.message : t('unknown_error')}</span>
          <button onClick={() => refetch()} className="ml-auto text-xs text-red-400 underline">{t('retry')}</button>
        </div>
      )}
      {/* Arka plan yenileme göstergesi */}
      {isFetching && !isLoading && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <div className="animate-spin rounded-full h-3 w-3 border-b border-slate-400"></div>
          {t('refreshing')}
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
                placeholder={t('search_host_vm_ip')}
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-72 bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-2 pl-10 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <span className="absolute left-3 top-2.5 text-slate-500"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg></span>
            </div>
            {/* Show Offline Toggle */}
            <label className="flex items-center space-x-2 cursor-pointer">
              <input
                type="checkbox"
                checked={showOffline}
                onChange={(e) => setShowOffline(e.target.checked)}
                className="w-4 h-4 text-blue-600 bg-white/[0.07] border-slate-600 rounded focus:ring-blue-500"
              />
              <span className="text-sm text-slate-300">{t('filter_show_offline')}</span>
            </label>
            {canSeeNameMismatch && (
              <label className="flex items-center space-x-2 cursor-pointer" title={t('filter_name_mismatch_hint')}>
                <input
                  type="checkbox"
                  checked={nameMismatchFilter}
                  onChange={(e) => setNameMismatchFilter(e.target.checked)}
                  className="w-4 h-4 text-amber-500 bg-white/[0.07] border-slate-600 rounded focus:ring-amber-500"
                />
                <span className="text-sm text-slate-300">
                  {t('filter_name_mismatch')}
                  {typeof linuxSummary?.name_mismatch === 'number' ? (
                    <span className="ml-1 text-amber-400/90">({linuxSummary.name_mismatch})</span>
                  ) : null}
                </span>
              </label>
            )}
            {/* Status Filter */}
            {showOffline && (
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="all">{t('filter_all_status')}</option>
                <option value="ONLINE">{t('status_online')}</option>
                <option value="OFFLINE">{t('status_offline')}</option>
                <option value="WARNING">{t('status_warning')}</option>
                <option value="CRITICAL">{t('status_critical')}</option>
              </select>
            )}
            {/* AI Ready Filter */}
            <select
              value={aiReadyFilter}
              onChange={(e) => setAiReadyFilter(e.target.value)}
              className="bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">{t('filter_all')}</option>
              <option value="true">{t('ai_ready')}</option>
              <option value="false">{t('ai_ready_not')}</option>
            </select>
            {/* Type Filter */}
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">{t('filter_all_types')}</option>
              <option value="VIRTUAL">Virtual</option>
              <option value="PHYSICAL">Physical</option>
            </select>
            {/* OS Filter */}
            <select
              value={osFilter}
              onChange={(e) => setOsFilter(e.target.value)}
              className="bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">{t('filter_all_os')}</option>
              <option value="linux">Linux</option>
              <option value="other">{t('filter_os_other')}</option>
            </select>
            {/* Node Exporter Filter */}
            <select
              value={nodeExporterFilter}
              onChange={(e) => setNodeExporterFilter(e.target.value)}
              className="bg-cyber-card border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">{t('node_exporter_all')}</option>
              <option value="running">{t('node_exporter_running')}</option>
              <option value="installed">{t('node_exporter_installed')}</option>
              <option value="not_installed">{t('node_exporter_missing')}</option>
            </select>

          </div>
          <div className="flex items-center gap-2">
            {selectedIds.size > 0 && (
              <span className="text-xs text-blue-400 bg-blue-500/10 border border-blue-500/25 px-2.5 py-1 rounded-lg">
                {t('selected_n', { n: selectedIds.size })}
              </span>
            )}
            <ActionsDropdown
              refetch={() => { refetch() }}
              selectedIds={selectedIdList}
              bulkJobId={bulkJobId}
              setBulkJobId={setBulkJobId}
              sshOpsEnabled={sshOpsEnabled}
            />
          </div>
        </div>
      </div>

      {!sshOpsEnabled && (
        <div className="text-xs text-amber-300/90 bg-amber-500/10 border border-amber-500/25 rounded-lg px-3 py-2">
          {t('ssh_cred_hint')} {t('ssh_cred_tcp_ok')}
        </div>
      )}

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
                <th className="relative px-2 py-3 text-left overflow-hidden">
                  <input
                    ref={selectAllRef}
                    type="checkbox"
                    checked={pageAllSelected}
                    onChange={toggleSelectAllPage}
                    className="w-4 h-4 text-blue-600 bg-white/[0.07] border-slate-600 rounded focus:ring-blue-500"
                    title={t('select_page_all')}
                  />
                  <div
                    className="absolute right-0 top-0 bottom-0 w-3 flex items-center justify-center cursor-col-resize group/rz hover:bg-blue-500/10"
                    onMouseDown={e => onResizeMouseDown(0, e)}
                  >
                    <div className="w-0.5 h-4 bg-slate-600 group-hover/rz:bg-blue-400 transition-colors rounded-full" />
                  </div>
                </th>
                {([
                  { key: 'name',   label: t('col_server'),     sortable: true,  sortKey: 'hostname' },
                  { key: 'tip',    label: t('col_type'),       sortable: true,  sortKey: 'type'   },
                  { key: 'status', label: t('col_status'),     sortable: true,  sortKey: 'status' },
                  { key: 'os',     label: 'OS',          sortable: true,  sortKey: 'os'     },
                  { key: 'cpu',    label: `CPU / ${t('memory')}`,   sortable: true,  sortKey: 'cpu'    },
                  { key: 'izleme', label: t('col_monitoring'),  sortable: true,  sortKey: 'ai'     },
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
                    {ci + 1 < colWidths.length - 1 && (
                      <div
                        className="absolute right-0 top-0 bottom-0 w-3 flex items-center justify-center cursor-col-resize group/rz hover:bg-blue-500/10"
                        onMouseDown={e => onResizeMouseDown(ci + 1, e)}
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
                  <td colSpan={8} className="px-6 py-12 text-center text-slate-400">
                    <p className="font-medium">{t('servers_empty')}</p>
                    <p className="text-sm mt-1">{t('servers_empty_hint')}</p>
                    <p className="text-xs mt-2 text-slate-500">API: {API_BASE_URL}</p>
                  </td>
                </tr>
              ) : sortedServers.map((server) => {
                const osLabelInput = {
                  os_type: server.os_type,
                  os_version: server.os_version,
                  os_release_id: server.os_release_id,
                  os_version_id: server.os_version_id,
                  os_pretty: server.os_version || server.vm_guest_os_full,
                  vm_guest_os_full: server.vm_guest_os_full,
                }
                const isSelected = selectedIds.has(server.id)
                return (
                <React.Fragment key={server.id}>
                <tr
                  className={`hover:bg-white/[0.02] transition-colors cursor-pointer border-b border-white/[0.06]/50 group ${isSelected ? 'bg-blue-500/10' : ''}`}
                  onClick={(e) => {
                    const el = e.target as HTMLElement
                    if (el.closest('button, a, input, label')) return
                    if (rowClickTimer.current) clearTimeout(rowClickTimer.current)
                    rowClickTimer.current = window.setTimeout(() => {
                      toggleSelect(server.id)
                      rowClickTimer.current = null
                    }, 200)
                  }}
                  onDoubleClick={(e) => {
                    e.preventDefault()
                    if (rowClickTimer.current) {
                      clearTimeout(rowClickTimer.current)
                      rowClickTimer.current = null
                    }
                    setSelectedServer(server)
                  }}
                  onContextMenu={(e) => {
                    e.preventDefault()
                    setContextMenu({ x: e.clientX, y: e.clientY, server })
                  }}
                >
                  <td className="px-2 py-3" onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(server.id)}
                      className="w-4 h-4 text-blue-600 bg-white/[0.07] border-slate-600 rounded focus:ring-blue-500"
                    />
                  </td>

                  {/* ── Hostname (birincil) + IP + VM adı ── */}
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <OsIcon os={osLabelInput} size={26} className="mt-0.5" />
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <div className="text-sm font-semibold text-white group-hover:text-blue-300 transition-colors truncate max-w-[180px]" title={displayHostname(server)}>
                            {displayHostname(server)}
                          </div>
                          {canSeeNameMismatch && hasNameMismatch(server) && (
                            <span
                              className="shrink-0 inline-flex items-center gap-0.5 text-[10px] font-medium text-amber-300 bg-amber-500/15 border border-amber-500/30 px-1.5 py-0.5 rounded"
                              title={t('vm_name_title', { name: server.vm_name || server.name })}
                            >
                              <AlertTriangle size={10} strokeWidth={2} />
                              {t('name_mismatch_short')}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                          <span className="text-xs font-mono text-slate-400">{server.ip_address || '-'}</span>
                          {displayVmLabel(server) && (
                            <span className="text-[11px] text-slate-500 truncate max-w-[140px]" title={`VM: ${displayVmLabel(server)!}`}>
                              VM: {displayVmLabel(server)}
                            </span>
                          )}
                          {server.hypervisor_name ? (
                            <span
                              className="inline-flex items-center gap-0.5 text-[11px] text-slate-500 bg-white/[0.07]/50 px-1.5 py-0.5 rounded"
                              title={
                                server.vcenter_endpoint
                                  ? `vCenter: ${server.hypervisor_name} (${server.vcenter_endpoint})`
                                  : `vCenter: ${server.hypervisor_name}`
                              }
                            >
                              <Cloud size={10} strokeWidth={2} /> {server.hypervisor_name}
                            </span>
                          ) : null}
                          {server.vm_host_name ? (
                            <span
                              className="inline-flex items-center gap-0.5 text-[11px] text-slate-500 bg-white/[0.07]/50 px-1.5 py-0.5 rounded"
                              title={`ESXi host: ${server.vm_host_name}`}
                            >
                              ESXi {server.vm_host_name}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  </td>

                  {/* ── Tip ── */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span className="text-sm text-slate-300">{
                      (server.server_type || '').toUpperCase() === 'PHYSICAL' ? t('type_physical')
                        : (server.server_type || '').toUpperCase() === 'VIRTUAL' ? t('type_virtual')
                          : serverTypeLabel(server.server_type)
                    }</span>
                  </td>

                  {/* ── Durum ── */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    {server.status === 'ONLINE' ? (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-green-500/15 text-green-400 border border-green-500/30">
                        <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
                        {t('status_online')}
                      </span>
                    ) : server.status === 'OFFLINE' ? (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-white/[0.07]/50 text-slate-400 border border-slate-600/50">
                        <span className="w-1.5 h-1.5 bg-slate-500 rounded-full" />
                        {t('status_offline')}
                      </span>
                    ) : (
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${getStatusBadge(server.status)}`}>
                        <span className="w-1.5 h-1.5 rounded-full bg-current" />
                        {server.status}
                      </span>
                    )}
                  </td>

                  {/* ── OS (Level 1 ile aynı: kısa etiket + hover tam ad) ── */}
                  <td className="px-4 py-3">
                    <div className="min-w-0">
                      <div
                        className="text-sm text-slate-200 truncate max-w-[200px]"
                        title={fullOsLabel(osLabelInput) || undefined}
                      >
                        {shortenOsLabel(osLabelInput)}
                      </div>
                      {server.kernel_version && (
                        <div
                          className="text-[11px] text-slate-500 font-mono truncate max-w-[200px] mt-0.5"
                          title={server.kernel_version}
                        >
                          {server.kernel_version}
                        </div>
                      )}
                    </div>
                  </td>

                  {/* ── CPU / Memory ── */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="space-y-1">
                      {server.cpu_cores > 0 ? (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-slate-400 w-7">CPU</span>
                          <span className="text-sm font-medium text-white">{server.cpu_cores}</span>
                          <span className="text-xs text-slate-500">{t('cores')}</span>
                        </div>
                      ) : (
                        <div className="text-xs text-slate-600">—</div>
                      )}
                      {server.memory_gb > 0 && (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-slate-400 w-14">{t('memory')}</span>
                          <span className="text-sm font-medium text-white">{server.memory_gb}</span>
                          <span className="text-xs text-slate-500">GB</span>
                        </div>
                      )}
                    </div>
                  </td>

                  {/* ── İzleme (AI Ready + Metrik) ── */}
                  <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                    <div className="flex flex-col gap-1">
                      {server.ai_ready ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 w-fit">
                          <ShieldCheck size={11} />
                          {t('ai_ready')}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-slate-500/10 text-slate-400 border border-slate-600/40 w-fit">
                          {t('ai_ready_not')}
                        </span>
                      )}
                      {server.node_exporter?.running || server.node_exporter?.installed ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-green-500/15 text-green-400 border border-green-500/25 w-fit">
                          <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
                          {t('metric_badge')}
                        </span>
                      ) : null}
                    </div>
                  </td>

                  {/* ── İşlemler ── */}
                  <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-1">
                      {server.status === 'ONLINE' && server.ip_address && (
                        <button
                          onClick={() => openSsh(server)}
                          className="px-2.5 py-1.5 text-xs bg-green-700/40 hover:bg-green-700 text-green-300 rounded-lg transition-colors font-mono"
                          title={t('ssh_terminal_title')}
                        >
                          SSH
                        </button>
                      )}
                      <button
                        onClick={() => setSelectedServer(server)}
                        className="px-2.5 py-1.5 text-xs bg-white/[0.07] hover:bg-slate-600 text-slate-200 rounded-lg transition-colors"
                        title={t('detail')}
                      >
                        {t('detail')}
                      </button>
                      <button
                        onClick={async () => {
                          if (await showConfirm(t('delete_server_confirm'))) {
                            deleteMutation.mutate(server.id)
                          }
                        }}
                        className="px-2.5 py-1.5 text-xs text-red-400 hover:text-white hover:bg-red-700 rounded-lg transition-colors"
                        title={t('delete')}
                      >
                        {t('delete')}
                      </button>
                    </div>
                  </td>
                </tr>
                </React.Fragment>
              )})}
            </tbody>
          </table>
        </div>
        {sortedServers.length === 0 && (
          <div className="text-center py-12 text-slate-500">
            {searchTerm || statusFilter !== 'all' || aiReadyFilter !== 'all' || typeFilter !== 'all' || nodeExporterFilter !== 'all' || nameMismatchFilter
              ? t('servers_filter_empty')
              : t('servers_none_integrations')}
          </div>
        )}
        {totalServers > 0 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-white/[0.06] text-sm text-slate-400">
            <span>
              {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, totalServers)} / {totalServers}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="px-3 py-1 rounded-lg bg-white/[0.05] border border-white/[0.08] disabled:opacity-40 hover:bg-white/[0.08]"
              >
                {t('page_prev')}
              </button>
              <span className="text-slate-500">
                {page} / {totalPages}
              </span>
              <button
                type="button"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                className="px-3 py-1 rounded-lg bg-white/[0.05] border border-white/[0.08] disabled:opacity-40 hover:bg-white/[0.08]"
              >
                {t('page_next')}
              </button>
            </div>
          </div>
        )}
      </div>

    </div>

      {contextMenu && (
        <div
          className="fixed z-[60] w-64 overflow-hidden rounded-xl border border-slate-600/80 bg-slate-900/95 shadow-2xl shadow-black/50 backdrop-blur-md"
          style={{
            left: Math.min(contextMenu.x, typeof window !== 'undefined' ? window.innerWidth - 280 : contextMenu.x),
            top: Math.min(contextMenu.y, typeof window !== 'undefined' ? window.innerHeight - 360 : contextMenu.y),
          }}
          onMouseDown={e => e.stopPropagation()}
        >
          <div className="border-b border-slate-700/80 bg-slate-800/60 px-3 py-2.5">
            <div className="flex items-center gap-2.5 min-w-0">
              <OsIcon
                os={{
                  os_type: contextMenu.server.os_type,
                  os_version: contextMenu.server.os_version,
                  os_release_id: contextMenu.server.os_release_id,
                  os_version_id: contextMenu.server.os_version_id,
                  os_pretty: contextMenu.server.os_version || contextMenu.server.vm_guest_os_full,
                  vm_guest_os_full: contextMenu.server.vm_guest_os_full,
                }}
                size={22}
              />
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-white">{contextMenu.server.name}</div>
                <div className="truncate font-mono text-[11px] text-slate-400">
                  {contextMenu.server.ip_address || '—'}
                  {getContextOpIds(contextMenu.server).length > 1
                    ? ` · ${t('selected_n', { n: getContextOpIds(contextMenu.server).length })}`
                    : ''}
                </div>
              </div>
            </div>
          </div>

          <div className="py-1.5">
            <div className="px-3 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              {t('actions')}
            </div>
            {([
              {
                label: t('ctx_check_health'),
                hint: t('ctx_check_health_hint'),
                icon: Activity,
                action: () => { setContextMenu(null); runCheckHealth(getContextOpIds(contextMenu.server)) },
              },
              {
                label: t('ai_ready_update'),
                hint: t('ai_ready_update_hint'),
                icon: ShieldCheck,
                disabled: !sshOpsEnabled,
                action: () => { setContextMenu(null); runAiReadyUpdate(getContextOpIds(contextMenu.server)) },
              },
              {
                label: t('os_refresh'),
                hint: t('os_refresh_hint'),
                icon: HardDrive,
                disabled: !sshOpsEnabled,
                action: () => { setContextMenu(null); runOsRefresh(getContextOpIds(contextMenu.server)) },
              },
            ] as Array<{ label: string; hint: string; icon: typeof Activity; action: () => void; disabled?: boolean }>).map(item => (
              <button
                key={item.label}
                type="button"
                disabled={item.disabled}
                title={item.disabled ? t('ssh_cred_hint') : item.hint}
                onClick={item.action}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-blue-500/10 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-800 text-slate-300 ring-1 ring-slate-700/80">
                  <item.icon size={14} />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm text-slate-100">{item.label}</span>
                  <span className="block text-[11px] text-slate-500">{item.hint}</span>
                </span>
              </button>
            ))}
          </div>

          <div className="mx-2 border-t border-slate-700/70" />

          <div className="py-1.5">
            {contextMenu.server.status === 'ONLINE' && contextMenu.server.ip_address && (
              <button
                type="button"
                onClick={() => { setContextMenu(null); openSsh(contextMenu.server) }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-emerald-500/10"
              >
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30">
                  <Terminal size={14} />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm text-slate-100">{t('ssh_terminal')}</span>
                  <span className="block text-[11px] text-slate-500">{t('ssh_terminal_hint')}</span>
                </span>
              </button>
            )}
            <button
              type="button"
              onClick={() => { setContextMenu(null); setSelectedServer(contextMenu.server) }}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-blue-500/10"
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-800 text-slate-300 ring-1 ring-slate-700/80">
                <Info size={14} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm text-slate-100">{t('detail')}</span>
                <span className="block text-[11px] text-slate-500">{t('detail_hint')}</span>
              </span>
            </button>
          </div>

          <div className="mx-2 border-t border-slate-700/70" />

          <div className="py-1.5 pb-2">
            <button
              type="button"
              onClick={async () => {
                const ids = getContextOpIds(contextMenu.server)
                setContextMenu(null)
                const msg = ids.length > 1
                  ? t('delete_servers_confirm', { n: ids.length })
                  : t('delete_server_confirm')
                if (!await showConfirm(msg)) return
                for (const id of ids) await deleteMutation.mutateAsync(id)
              }}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-red-500/10"
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-red-500/15 text-red-300 ring-1 ring-red-500/30">
                <Trash2 size={14} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm text-red-300">{t('delete')}</span>
                <span className="block text-[11px] text-red-400/70">{t('delete_hint')}</span>
              </span>
            </button>
          </div>
        </div>
      )}

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

