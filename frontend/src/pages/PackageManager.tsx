import React, { useState, useEffect, useRef, useCallback } from 'react'
import { AlertTriangle, CheckCircle2, XCircle, Lock, Lightbulb } from 'lucide-react'
import { useT, useLocale } from '../i18n/LocaleProvider'
import type { TranslationKey } from '../i18n/messages'

// ─── Types ──────────────────────────────────────────────────────────────────
interface PackageFile {
  id: number
  original_name: string
  file_size: number
  package_type: 'deb' | 'rpm' | 'unknown'
  description: string | null
  created_at: string
}

interface ServerItem {
  id: number
  name: string
  ip_address: string
  status: string
  os_type: string | null
  ai_ready: boolean
}

interface JobResult {
  status: 'success' | 'failed'
  output: string
  error: string
  duration: number
  server_name: string
  server_ip: string
  update_count?: number
}

interface Job {
  id: number
  job_type: 'deploy' | 'upgrade' | 'check_updates'
  status: 'pending' | 'running' | 'completed' | 'failed' | 'partial'
  title: string
  total_servers: number
  completed_servers: number
  created_at: string
  completed_at: string | null
  package_name: string | null
  results?: Record<string, JobResult>
  server_ids?: number[]
  live_log?: Record<string, string>
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
const API = '/api/v1'
const authHeaders = (): Record<string, string> => {
  const t = localStorage.getItem('auth_token')
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (t) h['Authorization'] = `Bearer ${t}`
  return h
}
const fmtSize = (b: number) => b > 1_048_576 ? `${(b/1_048_576).toFixed(1)} MB` : `${(b/1024).toFixed(0)} KB`
const dateLoc = (locale: string) => locale === 'en' ? 'en-GB' : 'tr-TR'
const fmtDate = (s: string, locale: string) => new Date(s).toLocaleString(dateLoc(locale))

const STATUS_COLOR: Record<string, string> = {
  pending:   'bg-yellow-500/20 text-yellow-300 border-yellow-500/40',
  running:   'bg-blue-500/20   text-blue-300   border-blue-500/40',
  completed: 'bg-green-500/20  text-green-300  border-green-500/40',
  failed:    'bg-red-500/20    text-red-300    border-red-500/40',
  partial:   'bg-orange-500/20 text-orange-300 border-orange-500/40',
}

const STATUS_KEYS: Record<string, TranslationKey> = {
  pending: 'pkg_status_pending', running: 'pkg_status_running',
  completed: 'pkg_status_completed', failed: 'failed', partial: 'pkg_status_partial',
}

const JOB_TYPE_KEYS: Record<string, TranslationKey> = {
  deploy: 'pkg_job_deploy',
  upgrade: 'pkg_job_upgrade',
  check_updates: 'pkg_job_check',
}

// ─── Sub-components ──────────────────────────────────────────────────────────

const StatusBadge = ({ status }: { status: string }) => {
  const t = useT()
  return (
  <span className={`px-2 py-0.5 text-xs rounded-full border font-medium ${STATUS_COLOR[status] || 'bg-white/[0.07] text-slate-300 border-slate-600'}`}>
    {STATUS_KEYS[status] ? t(STATUS_KEYS[status]) : status}
  </span>
  )
}

const ProgressBar = ({ done, total }: { done: number; total: number }) => {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-white/[0.07] rounded-full h-1.5">
        <div className="bg-blue-500 h-1.5 rounded-full transition-all" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-400 whitespace-nowrap">{done}/{total}</span>
    </div>
  )
}

// Server multi-select
const ServerSelector = ({
  servers, selected, onChange,
}: {
  servers: ServerItem[]
  selected: number[]
  onChange: (ids: number[]) => void
}) => {
  const t = useT()
  const [search, setSearch] = useState('')
  const [onlyAiReady, setOnlyAiReady] = useState(true)

  const aiReadyCount = servers.filter(s => s.ai_ready).length

  const filtered = servers.filter(s => {
    const matchSearch = s.name.toLowerCase().includes(search.toLowerCase()) || s.ip_address.includes(search)
    const matchAi = !onlyAiReady || s.ai_ready
    return matchSearch && matchAi
  })

  const toggle = (id: number) =>
    onChange(selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id])

  const selectAll     = () => onChange(filtered.map(s => s.id))
  const selectOnline  = () => onChange(filtered.filter(s => s.status === 'ONLINE').map(s => s.id))
  const selectAiReady = () => onChange(servers.filter(s => s.ai_ready && s.status === 'ONLINE').map(s => s.id))
  const clearAll      = () => onChange([])

  return (
    <div className="border border-white/[0.06] rounded-lg overflow-hidden">
      {/* Toolbar */}
      <div className="bg-cyber-card px-3 py-2 flex flex-wrap items-center gap-2 border-b border-white/[0.06]">
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder={t('pkg_search_server')}
          className="flex-1 min-w-[140px] bg-white/[0.07] text-white text-sm px-3 py-1.5 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
        />
        {/* AI Ready toggle */}
        <button
          onClick={() => setOnlyAiReady(!onlyAiReady)}
          className={`flex items-center gap-1 text-xs px-2 py-1 rounded border transition-colors ${
            onlyAiReady
              ? 'bg-green-500/15 text-green-300 border-green-500/40'
              : 'bg-white/[0.07] text-slate-400 border-slate-600 hover:text-slate-200'
          }`}
          title={onlyAiReady ? t('pkg_show_all_servers') : t('pkg_show_ai_ready_only')}
        >
          AI Ready {onlyAiReady && <span className="font-bold">{aiReadyCount}</span>}
        </button>
      </div>

      {/* Hızlı seçim */}
      <div className="bg-cyber-card/60 px-3 py-1.5 flex items-center gap-2 border-b border-white/[0.06]">
        <button onClick={selectAiReady} className="text-xs text-green-400 hover:text-green-300 px-2.5 py-1.5 hover:bg-white/[0.06] rounded">{t('pkg_select_ai_ready')}</button>
        <button onClick={selectOnline}  className="text-xs text-blue-400 hover:text-blue-300 px-2.5 py-1.5 hover:bg-white/[0.06] rounded">{t('pkg_select_online')}</button>
        <button onClick={selectAll}     className="text-xs text-slate-400 hover:text-slate-300 px-2.5 py-1.5 hover:bg-white/[0.06] rounded">{t('filter_all')}</button>
        <button onClick={clearAll}      className="text-xs text-slate-500 hover:text-slate-300 px-2.5 py-1.5 hover:bg-white/[0.06] rounded">{t('pkg_clear')}</button>
        <span className="text-xs text-slate-500 ml-auto">{t('selected_n', { n: selected.length })}</span>
      </div>

      {/* List */}
      <div className="max-h-56 overflow-y-auto divide-y divide-white/[0.04]">
        {filtered.length === 0 && (
          <div className="px-4 py-6 text-center text-slate-500 text-sm">
            {onlyAiReady ? (
              <span>{t('pkg_no_ai_ready')}{' '}
                <button onClick={() => setOnlyAiReady(false)} className="text-blue-400 underline">{t('pkg_show_all_link')}</button>
              </span>
            ) : t('pkg_no_servers')}
          </div>
        )}
        {filtered.map(srv => (
          <label
            key={srv.id}
            className={`flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-white/[0.04] transition-colors ${selected.includes(srv.id) ? 'bg-blue-600/10' : ''}`}
          >
            <input
              type="checkbox"
              checked={selected.includes(srv.id)}
              onChange={() => toggle(srv.id)}
              className="accent-blue-500 w-4 h-4 flex-shrink-0"
            />
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${srv.status === 'ONLINE' ? 'bg-green-400' : 'bg-slate-500'}`} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-sm text-white font-medium truncate">{srv.name}</span>
                {srv.ai_ready && <span className="text-[10px] text-green-400 flex-shrink-0 font-bold">AI</span>}
              </div>
              <div className="text-xs text-slate-400">{srv.ip_address}{srv.os_type ? ` · ${srv.os_type}` : ''}</div>
            </div>
          </label>
        ))}
      </div>
    </div>
  )
}

// Canlı log paneli (çalışan sunucu için)
const LiveLogPane = ({ logText }: { serverId: string; logText: string }) => {
  const logRef = useRef<HTMLPreElement>(null)
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logText])
  const lines = logText.trim().split('\n')
  const lastLines = lines.slice(-80)  // son 80 satır
  return (
    <pre
      ref={logRef}
      className="bg-slate-950 px-3 py-2 text-xs text-green-300 font-mono max-h-56 overflow-y-auto whitespace-pre-wrap leading-relaxed"
    >
      {lastLines.join('\n')}
    </pre>
  )
}

// Job result expandable row
const JobResultRow = ({ result }: { sid: string; result: JobResult }) => {
  const t = useT()
  const [open, setOpen] = useState(false)
  const isOk = result.status === 'success'
  return (
    <div className="border border-white/[0.06] rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/[0.03] transition-colors text-left"
      >
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${isOk ? 'bg-green-400' : 'bg-red-400'}`} />
        <div className="flex-1 min-w-0">
          <span className="text-sm font-medium text-white">{result.server_name}</span>
          <span className="text-xs text-slate-400 ml-2">{result.server_ip}</span>
        </div>
        {result.update_count !== undefined && (
          <span className="text-xs text-yellow-400 bg-yellow-500/10 border border-yellow-500/30 px-2 py-0.5 rounded-full">
            {t('pkg_n_updates', { n: result.update_count })}
          </span>
        )}
        <span className={`text-xs px-2 py-0.5 rounded-full border ${isOk ? 'text-green-300 bg-green-500/10 border-green-500/30' : 'text-red-300 bg-red-500/10 border-red-500/30'}`}>
          {isOk ? t('pkg_ok') : t('error_generic')}
        </span>
        <span className="text-xs text-slate-500">{result.duration}s</span>
        <span className="text-slate-500">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="border-t border-white/[0.06] bg-slate-950 px-4 py-3">
          {result.output && (
            <pre className="text-xs text-slate-300 whitespace-pre-wrap font-mono max-h-64 overflow-y-auto">{result.output}</pre>
          )}
          {result.error && (
            <pre className="text-xs text-red-400 whitespace-pre-wrap font-mono mt-2 max-h-32 overflow-y-auto">{result.error}</pre>
          )}
          {!result.output && !result.error && (
            <span className="text-xs text-slate-500 italic">{t('pkg_no_output')}</span>
          )}
        </div>
      )}
    </div>
  )
}

// Full job card in history
const JobCard = ({ job, onDelete, onExpand }: {
  job: Job
  onDelete: (id: number) => void
  onExpand: (id: number) => void
}) => {
  const t = useT()
  const { locale } = useLocale()
  const isRunning = job.status === 'running' || job.status === 'pending'
  return (
    <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-mono text-slate-500 bg-white/[0.07] px-1.5 py-0.5 rounded">#{job.id}</span>
            <span className="text-xs text-slate-400">{JOB_TYPE_KEYS[job.job_type] ? t(JOB_TYPE_KEYS[job.job_type]) : job.job_type}</span>
            <StatusBadge status={job.status} />
            {isRunning && <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse" />}
          </div>
          <div className="text-sm text-white font-medium mt-1 truncate">{job.title}</div>
          <div className="text-xs text-slate-500 mt-0.5">{fmtDate(job.created_at, locale)}</div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={() => onExpand(job.id)}
            className="text-xs text-blue-400 hover:text-blue-300 px-3 py-1.5 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/30 rounded-lg transition-colors"
          >
            {t('detail')}
          </button>
          {!isRunning && (
            <button
              onClick={() => onDelete(job.id)}
              className="text-xs text-red-400 hover:text-red-300 px-3 py-1.5 bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 rounded-lg transition-colors"
            >
              {t('delete')}
            </button>
          )}
        </div>
      </div>
      <div className="mt-3">
        <ProgressBar done={job.completed_servers} total={job.total_servers} />
      </div>
    </div>
  )
}

// ─── Confirm Modal ───────────────────────────────────────────────────────────
const ConfirmModal = ({ message, onConfirm, onCancel }: {
  message: string
  onConfirm: () => void
  onCancel: () => void
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
        <button
          onClick={onCancel}
          className="px-4 py-2 rounded-lg text-sm text-slate-300 hover:text-white bg-white/[0.07] hover:bg-slate-600 border border-slate-600 transition-colors"
        >
          {t('cancel')}
        </button>
        <button
          onClick={onConfirm}
          className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-red-600 hover:bg-red-500 border border-red-500/50 transition-colors"
        >
          {t('confirm_ok')}
        </button>
      </div>
    </div>
  </div>
  )
}

// ─── Main Page ───────────────────────────────────────────────────────────────
const PackageManager: React.FC = () => {
  const t = useT()
  const { locale } = useLocale()
  const [tab, setTab] = useState<'deploy' | 'history'>('deploy')

  // Data
  const [packageFiles, setPackageFiles] = useState<PackageFile[]>([])
  const [servers, setServers] = useState<ServerItem[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [expandedJob, setExpandedJob] = useState<Job | null>(null)

  // Deploy tab
  const [selectedPkgId, setSelectedPkgId] = useState<number | null>(null)
  const [deployServers, setDeployServers] = useState<number[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadDesc, setUploadDesc] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  // Yetkili Kullanıcı (deploy için)
  const [credMode, setCredMode] = useState<'stored' | 'override'>('stored')
  const [overrideUser, setOverrideUser] = useState('')
  const [overridePass, setOverridePass] = useState('')
  const [overrideSudo, setOverrideSudo] = useState('')

  // Loading states
  const [deploying, setDeploying] = useState(false)
  const [toast, setToast] = useState<{ msg: string; type: 'ok' | 'err' } | null>(null)

  // AI Analysis
  const [aiAnalysis, setAiAnalysis] = useState<Record<number, string>>({})
  const [aiLoading, setAiLoading] = useState<number | null>(null)

  // Custom confirm modal
  const [confirmState, setConfirmState] = useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const showConfirm = (msg: string): Promise<boolean> =>
    new Promise(resolve => setConfirmState({ msg, resolve }))
  const handleConfirmOk     = () => { confirmState?.resolve(true);  setConfirmState(null) }
  const handleConfirmCancel = () => { confirmState?.resolve(false); setConfirmState(null) }

  const toastTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const showToast = (msg: string, type: 'ok' | 'err' = 'ok') => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
    setToast({ msg, type })
    toastTimerRef.current = setTimeout(() => setToast(null), 4000)
  }

  // Toast timer temizle (unmount)
  React.useEffect(() => () => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
  }, [])

  // ── Fetch helpers ──────────────────────────────────────────────────────────
  const loadFiles = useCallback(() =>
    fetch(`${API}/packages/files`, { headers: authHeaders() })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setPackageFiles)
      .catch((e: Error) => showToast(t('pkg_load_files_fail', { msg: e.message }), 'err')), []) // eslint-disable-line react-hooks/exhaustive-deps

  const loadServers = useCallback(() =>
    fetch(`${API}/servers/?page=1&page_size=200&ai_ready=true`, { headers: authHeaders() })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((data: any) => {
        const list: any[] = Array.isArray(data) ? data : (data?.servers || data?.items || [])
        setServers(list.map(s => ({
          id: s.id, name: s.name, ip_address: s.ip_address,
          status: s.status, os_type: s.os_type, ai_ready: !!s.ai_ready,
        })))
      })
      .catch((e: Error) => showToast(t('pkg_load_servers_fail', { msg: e.message }), 'err')), []) // eslint-disable-line react-hooks/exhaustive-deps

  const loadJobs = useCallback(() =>
    fetch(`${API}/packages/jobs?limit=100`, { headers: authHeaders() })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setJobs)
      .catch((e: Error) => console.warn('İşler yüklenemedi:', e.message)), []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    loadFiles(); loadServers(); loadJobs()
  }, [loadFiles, loadServers, loadJobs])

  // Auto-refresh jobs while any are running
  useEffect(() => {
    const hasRunning = jobs.some(j => j.status === 'pending' || j.status === 'running')
    if (!hasRunning) return
    const t = setInterval(loadJobs, 3000)
    return () => clearInterval(t)
  }, [jobs, loadJobs])

  // Refresh expanded job — job ID'yi capture et, stale closure'dan korun
  useEffect(() => {
    if (!expandedJob) return
    if (expandedJob.status !== 'running' && expandedJob.status !== 'pending') return
    const jobId = expandedJob.id
    let active = true
    const t = setInterval(async () => {
      if (!active) return
      try {
        const r = await fetch(`${API}/packages/jobs/${jobId}`, { headers: authHeaders() })
        if (r.ok && active) setExpandedJob(await r.json())
      } catch {
        // bağlantı hatası — sessizce atla, bir sonraki interval'da tekrar dene
      }
    }, 2000)
    return () => {
      active = false
      clearInterval(t)
    }
  }, [expandedJob?.id, expandedJob?.status])

  // ── Upload ─────────────────────────────────────────────────────────────────
  const handleFileDrop = async (file: File) => {
    if (!file.name.match(/\.(deb|rpm)$/i)) {
      showToast(t('pkg_upload_type_err'), 'err'); return
    }
    setUploading(true)
    const fd = new FormData()
    fd.append('file', file)
    fd.append('description', uploadDesc)
    try {
      const r = await fetch(`${API}/packages/files/upload`, { method: 'POST', body: fd, headers: { 'Authorization': `Bearer ${localStorage.getItem('auth_token') || ''}` } })
      if (!r.ok) throw new Error((await r.json()).detail)
      showToast(t('pkg_uploaded', { name: file.name }))
      setUploadDesc('')
      await loadFiles()
    } catch (e: any) {
      showToast(e.message || t('pkg_upload_err'), 'err')
    } finally {
      setUploading(false)
    }
  }

  const handleDeleteFile = async (id: number) => {
    if (!await showConfirm(t('pkg_delete_file_confirm'))) return
    await fetch(`${API}/packages/files/${id}`, { method: 'DELETE', headers: authHeaders() })
    await loadFiles()
  }

  // ── Deploy ─────────────────────────────────────────────────────────────────
  const handleDeploy = async () => {
    if (!selectedPkgId) { showToast(t('pkg_select_pkg'), 'err'); return }
    if (deployServers.length === 0) { showToast(t('pkg_select_server'), 'err'); return }
    if (credMode === 'override' && !overrideUser.trim()) {
      showToast(t('pkg_override_user_required'), 'err'); return
    }
    setDeploying(true)
    const body: any = { package_file_id: selectedPkgId, server_ids: deployServers }
    if (credMode === 'override') {
      body.override_user         = overrideUser.trim() || undefined
      body.override_password     = overridePass || undefined
      body.override_sudo_password = overrideSudo || overridePass || undefined
    }
    try {
      const r = await fetch(`${API}/packages/jobs/deploy`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify(body),
      })
      if (!r.ok) throw new Error((await r.json()).detail)
      showToast(t('pkg_deploy_started'))
      await loadJobs()
      setTab('history')
    } catch (e: any) {
      showToast(e.message || t('error_generic'), 'err')
    } finally {
      setDeploying(false)
    }
  }

  // ── Job actions ────────────────────────────────────────────────────────────
  const handleDeleteJob = async (id: number) => {
    if (!await showConfirm(t('pkg_delete_job_confirm'))) return
    await fetch(`${API}/packages/jobs/${id}`, { method: 'DELETE', headers: authHeaders() })
    await loadJobs()
    if (expandedJob?.id === id) setExpandedJob(null)
  }

  const handleExpandJob = async (id: number) => {
    const r = await fetch(`${API}/packages/jobs/${id}`)
    if (r.ok) setExpandedJob(await r.json())
  }

  const handleAiAnalyze = async (jobId: number) => {
    setAiLoading(jobId)
    setAiAnalysis(prev => ({ ...prev, [jobId]: '' }))
    try {
      const r = await fetch(`${API}/packages/jobs/${jobId}/analyze-error`, { method: 'POST', headers: authHeaders() })
      const data = await r.json()
      if (!r.ok) throw new Error(data.detail || t('pkg_ai_fail'))
      setAiAnalysis(prev => ({ ...prev, [jobId]: data.analysis }))
    } catch (e: any) {
      setAiAnalysis(prev => ({ ...prev, [jobId]: t('pkg_ai_err', { msg: e.message }) }))
    } finally {
      setAiLoading(null)
    }
  }

  const runningCount = jobs.filter(j => j.status === 'running' || j.status === 'pending').length

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Custom Confirm Modal */}
      {confirmState && (
        <ConfirmModal
          message={confirmState.msg}
          onConfirm={handleConfirmOk}
          onCancel={handleConfirmCancel}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">{t('pkg_title')}</h1>
          <p className="text-slate-400 text-sm mt-1">{t('pkg_subtitle')}</p>
        </div>
        {runningCount > 0 && (
          <div className="flex items-center gap-2 bg-blue-500/10 border border-blue-500/30 px-3 py-2 rounded-lg">
            <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse" />
            <span className="text-sm text-blue-300">{t('pkg_jobs_running', { n: runningCount })}</span>
          </div>
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-xl border shadow-lg text-sm font-medium transition-all ${
          toast.type === 'ok'
            ? 'bg-green-900/90 border-green-500/50 text-green-300'
            : 'bg-red-900/90 border-red-500/50 text-red-300'
        }`}>
          <span className="inline-flex items-center gap-1.5">
            {toast.type === 'ok' ? <CheckCircle2 size={14} strokeWidth={2} /> : <XCircle size={14} strokeWidth={2} />}
            {toast.msg}
          </span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-cyber-card p-1 rounded-xl w-fit border border-white/[0.06]">
        {([
          { key: 'deploy', label: t('pkg_tab_deploy') },
          { key: 'history', label: `${t('pkg_tab_history')} ${jobs.length > 0 ? `(${jobs.length})` : ''}` },
        ] as const).map(tb => (
          <button
            key={tb.key}
            onClick={() => setTab(tb.key)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              tab === tb.key
                ? 'bg-blue-600 text-white shadow'
                : 'text-slate-400 hover:text-white hover:bg-white/[0.06]'
            }`}
          >
            {tb.label}
          </button>
        ))}
      </div>

      {/* ── TAB: Deploy ─────────────────────────────────────────────────── */}
      {tab === 'deploy' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left: Upload + Package List */}
          <div className="space-y-4">
            <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-5 space-y-4">
              <h2 className="text-base font-semibold text-white">{t('pkg_upload')}</h2>

              {/* Drop zone */}
              <div
                onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={e => {
                  e.preventDefault(); setDragOver(false)
                  const f = e.dataTransfer.files[0]
                  if (f) handleFileDrop(f)
                }}
                onClick={() => fileRef.current?.click()}
                className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
                  dragOver
                    ? 'border-blue-400 bg-blue-500/10'
                    : 'border-slate-600 hover:border-slate-500 hover:bg-white/[0.03]'
                }`}
              >
                <input
                  ref={fileRef} type="file" accept=".deb,.rpm" className="hidden"
                  onChange={e => { const f = e.target.files?.[0]; if (f) handleFileDrop(f) }}
                />
                {uploading ? (
                  <div className="flex flex-col items-center gap-2">
                    <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                    <span className="text-sm text-slate-400">{t('pkg_uploading')}</span>
                  </div>
                ) : (
                  <>
                    <div className="text-2xl font-bold text-blue-400 mb-2">PKG</div>
                    <div className="text-sm text-white font-medium">{t('pkg_drop')}</div>
                    <div className="text-xs text-slate-400 mt-1">{t('pkg_drop_hint')}</div>
                  </>
                )}
              </div>

              <input
                value={uploadDesc}
                onChange={e => setUploadDesc(e.target.value)}
                placeholder={t('pkg_desc_optional')}
                className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
              />
            </div>

            {/* Package list */}
            <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] overflow-hidden">
              <div className="px-4 py-3 border-b border-white/[0.06] flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white">{t('pkg_installed')}</h2>
                <span className="text-xs text-slate-500">{t('pkg_count', { n: packageFiles.length })}</span>
              </div>
              {packageFiles.length === 0 ? (
                <div className="px-4 py-8 text-center text-slate-500 text-sm">{t('pkg_none_yet')}</div>
              ) : (
                <div className="divide-y divide-white/[0.04]">
                  {packageFiles.map(pkg => (
                    <div
                      key={pkg.id}
                      onClick={() => setSelectedPkgId(pkg.id === selectedPkgId ? null : pkg.id)}
                      className={`flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors ${
                        selectedPkgId === pkg.id ? 'bg-blue-600/15 border-l-2 border-blue-500' : 'hover:bg-white/[0.03]'
                      }`}
                    >
                      
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-white font-medium truncate">{pkg.original_name}</div>
                        <div className="text-xs text-slate-400">{fmtSize(pkg.file_size)} · {pkg.package_type.toUpperCase()} · {fmtDate(pkg.created_at, locale)}</div>
                        {pkg.description && <div className="text-xs text-slate-500 italic mt-0.5">{pkg.description}</div>}
                      </div>
                      <button
                        onClick={e => { e.stopPropagation(); handleDeleteFile(pkg.id) }}
                        className="text-xs text-red-400 hover:text-red-300 px-2 py-1 hover:bg-red-500/10 rounded transition-colors flex-shrink-0"
                      >
                        {t('delete')}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right: Server selection + deploy button */}
          <div className="space-y-4">
            <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-semibold text-white">{t('pkg_target_servers')}</h2>
                {selectedPkgId && (
                  <span className="text-xs text-blue-300 bg-blue-500/10 border border-blue-500/30 px-2 py-1 rounded-lg">
                    {packageFiles.find(p => p.id === selectedPkgId)?.original_name}
                  </span>
                )}
              </div>

              {!selectedPkgId && (
                <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg px-3 py-2 text-xs text-yellow-300">
                  {t('pkg_pick_left')}
                </div>
              )}

              <ServerSelector servers={servers} selected={deployServers} onChange={setDeployServers} />

              {/* ── Yetkili Kullanıcı ───────────────────────────────────── */}
              <div className="border border-slate-600 rounded-xl overflow-hidden">
                <div className="bg-white/[0.07]/50 px-4 py-2.5 flex items-center gap-2 border-b border-slate-600">
                  <span className="flex items-center gap-1 text-xs font-semibold text-slate-300"><Lock size={11} strokeWidth={2} /> {t('pkg_priv_user')}</span>
                  <span className="text-xs text-slate-500">{t('pkg_priv_ssh')}</span>
                </div>
                <div className="p-3 space-y-2">
                  {/* Seçenek: kayıtlı */}
                  <label className={`flex items-start gap-3 p-3 rounded-lg border-2 cursor-pointer transition-all ${
                    credMode === 'stored'
                      ? 'border-green-500/60 bg-green-500/8'
                      : 'border-slate-600 hover:border-slate-500 bg-white/[0.02]'
                  }`}>
                    <input type="radio" checked={credMode === 'stored'} onChange={() => setCredMode('stored')}
                      className="accent-green-500 w-4 h-4 mt-0.5 flex-shrink-0" />
                    <div>
                      <div className="text-sm font-medium text-white">{t('pkg_use_stored')}</div>
                      <div className="text-xs text-slate-400 mt-0.5">{t('pkg_use_stored_hint')}</div>
                    </div>
                  </label>

                  {/* Seçenek: override */}
                  <label className={`flex items-start gap-3 p-3 rounded-lg border-2 cursor-pointer transition-all ${
                    credMode === 'override'
                      ? 'border-blue-500/60 bg-blue-500/8'
                      : 'border-slate-600 hover:border-slate-500 bg-white/[0.02]'
                  }`}>
                    <input type="radio" checked={credMode === 'override'} onChange={() => setCredMode('override')}
                      className="accent-blue-500 w-4 h-4 mt-0.5 flex-shrink-0" />
                    <div className="flex-1" onClick={e => e.stopPropagation()}>
                      <div className="text-sm font-medium text-white">{t('pkg_use_override')}</div>
                      <div className="text-xs text-slate-400 mt-0.5 mb-2">{t('pkg_use_override_hint')}</div>
                      {credMode === 'override' && (
                        <div className="space-y-2 mt-1">
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">{t('pkg_username')} <span className="text-red-400">*</span></label>
                            <input
                              value={overrideUser} onChange={e => setOverrideUser(e.target.value)}
                              placeholder={t('pkg_username_ph')}
                              className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
                            />
                          </div>
                          <div className="grid grid-cols-2 gap-2">
                            <div>
                              <label className="text-xs text-slate-400 block mb-1">{t('pkg_ssh_password')}</label>
                              <input
                                type="password" value={overridePass} onChange={e => setOverridePass(e.target.value)}
                                placeholder={t('pkg_ssh_password')}
                                className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
                              />
                            </div>
                            <div>
                              <label className="text-xs text-slate-400 block mb-1">
                                {t('pkg_sudo_password')} <span className="text-slate-500">{t('pkg_sudo_empty_hint')}</span>
                              </label>
                              <input
                                type="password" value={overrideSudo} onChange={e => setOverrideSudo(e.target.value)}
                                placeholder={t('pkg_sudo_ph')}
                                className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
                              />
                            </div>
                          </div>
                          <div className="flex items-start gap-1.5 bg-blue-500/8 border border-blue-500/20 rounded-lg px-3 py-2 text-xs text-blue-300">
                            <Lightbulb size={12} strokeWidth={2} className="flex-shrink-0 mt-0.5" />
                            <span>{t('pkg_root_sudo_hint')}</span>
                          </div>
                        </div>
                      )}
                    </div>
                  </label>
                </div>
              </div>

              <button
                onClick={handleDeploy}
                disabled={deploying || !selectedPkgId || deployServers.length === 0}
                className="w-full py-3 rounded-xl font-semibold text-sm transition-all bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {deploying
                  ? <><div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />{t('pkg_deploying')}</>
                  : <>{deployServers.length > 0 ? t('pkg_deploy_n', { n: deployServers.length }) : t('pkg_deploy')}</>
                }
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── TAB: Upgrade ────────────────────────────────────────────────── */}
      {/* ── TAB: History ────────────────────────────────────────────────── */}
      {tab === 'history' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Job list */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-300">{t('pkg_jobs', { n: jobs.length })}</h2>
              <button onClick={loadJobs} className="text-xs text-slate-400 hover:text-white px-2 py-1 hover:bg-white/[0.06] rounded transition-colors">
                {t('refresh_action')}
              </button>
            </div>
            {jobs.length === 0 ? (
              <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-8 text-center text-slate-500 text-sm">
                {t('pkg_no_jobs')}
              </div>
            ) : (
              jobs.map(job => (
                <JobCard key={job.id} job={job} onDelete={handleDeleteJob} onExpand={handleExpandJob} />
              ))
            )}
          </div>

          {/* Job detail */}
          <div>
            {expandedJob ? (
              <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] overflow-hidden sticky top-0">
                <div className="px-4 py-3 border-b border-white/[0.06] flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-mono text-slate-500 bg-white/[0.07] px-1.5 py-0.5 rounded">#{expandedJob.id}</span>
                      <span className="text-xs text-slate-400">{JOB_TYPE_KEYS[expandedJob.job_type] ? t(JOB_TYPE_KEYS[expandedJob.job_type]) : expandedJob.job_type}</span>
                      <StatusBadge status={expandedJob.status} />
                    </div>
                    <div className="text-sm font-medium text-white mt-0.5">{expandedJob.title}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    {(expandedJob.status === 'failed' || expandedJob.status === 'partial') && (
                      <button
                        onClick={() => handleAiAnalyze(expandedJob.id)}
                        disabled={aiLoading === expandedJob.id}
                        className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/40 text-blue-300 transition-colors disabled:opacity-50"
                      >
                        {aiLoading === expandedJob.id
                          ? <><div className="w-3 h-3 border border-blue-400/40 border-t-blue-300 rounded-full animate-spin" />{t('pkg_analyzing')}</>
                          : <>{t('pkg_ai_analyze')}</>
                        }
                      </button>
                    )}
                    <button onClick={() => setExpandedJob(null)} className="text-slate-400 hover:text-white text-xl leading-none">×</button>
                  </div>
                </div>

                {/* AI Analiz Sonucu */}
                {aiAnalysis[expandedJob.id] && (
                  <div className="border-b border-white/[0.06]">
                    <div className="bg-blue-900/20 px-4 py-2.5 flex items-center gap-2 border-b border-blue-500/20">
                      <span className="text-xs font-bold text-blue-400">AI</span>
                      <span className="text-xs font-semibold text-blue-300">{t('pkg_ai_solution')}</span>
                      <button
                        onClick={() => setAiAnalysis(prev => { const n = {...prev}; delete n[expandedJob.id]; return n })}
                        className="ml-auto text-slate-500 hover:text-white text-sm leading-none"
                      >×</button>
                    </div>
                    <div className="px-4 py-3 bg-blue-950/20 max-h-72 overflow-y-auto">
                      <div className="text-xs text-slate-200 whitespace-pre-wrap leading-relaxed font-mono">
                        {aiAnalysis[expandedJob.id]}
                      </div>
                    </div>
                  </div>
                )}

                <div className="p-4">
                  <div className="grid grid-cols-2 gap-3 mb-4 text-xs">
                    <div className="bg-white/[0.07]/50 rounded-lg p-2">
                      <div className="text-slate-400">{t('pkg_started')}</div>
                      <div className="text-white mt-0.5">{fmtDate(expandedJob.created_at, locale)}</div>
                    </div>
                    {expandedJob.completed_at && (
                      <div className="bg-white/[0.07]/50 rounded-lg p-2">
                        <div className="text-slate-400">{t('pkg_ended')}</div>
                        <div className="text-white mt-0.5">{fmtDate(expandedJob.completed_at, locale)}</div>
                      </div>
                    )}
                  </div>

                  <ProgressBar done={expandedJob.completed_servers} total={expandedJob.total_servers} />

                  {/* Canlı Log Akışı */}
                  {(expandedJob.status === 'running' || expandedJob.status === 'pending') &&
                    Object.keys(expandedJob.live_log || {}).length > 0 && (
                    <div className="mt-4 border border-blue-500/30 rounded-xl overflow-hidden">
                      <div className="bg-blue-500/10 px-3 py-2 flex items-center gap-2 border-b border-blue-500/20">
                        <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse" />
                        <span className="text-xs font-semibold text-blue-300">{t('pkg_live_log')}</span>
                      </div>
                      {Object.entries(expandedJob.live_log || {}).map(([sid, logText]) => (
                        <LiveLogPane key={sid} serverId={sid} logText={logText as string} />
                      ))}
                    </div>
                  )}

                  <div className="mt-4 space-y-2">
                    {Object.entries(expandedJob.results || {}).map(([sid, res]) => (
                      <JobResultRow key={sid} sid={sid} result={res as JobResult} />
                    ))}
                    {Object.keys(expandedJob.results || {}).length === 0 && (
                      <div className="text-xs text-slate-500 text-center py-4 italic">
                        {expandedJob.status === 'pending' || expandedJob.status === 'running'
                          ? t('pkg_job_running')
                          : t('pkg_no_results')}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-8 text-center text-slate-500 text-sm">
                {t('pkg_pick_job')}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default PackageManager
