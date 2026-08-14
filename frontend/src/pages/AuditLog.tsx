import React, { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import { lazyWithRetry } from '../lib/lazyWithRetry'
import { useT, useLocale } from '../i18n/LocaleProvider'
import type { TranslationKey } from '../i18n/messages'
import './level1/level1-theme.css'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Task {
  id: string
  type: 'snapshot' | 'agent' | 'package' | 'update' | 'error'
  title: string
  subtitle?: string
  preview?: string
  status: string
  platform?: string
  source?: string
  retention?: string
  snapshot_id?: string
  error_message?: string
  risk_level?: string
  requires_root?: boolean
  decided_by?: string
  step?: string
  created_at: string | null
  decided_at?: string | null
  executed_at?: string | null
  age: string
  server_id?: number | null
  raw_id?: number
}

interface TaskSummary {
  total: number
  pending: number
  running: number
  failed: number
  active: number
}

interface AuditRow {
  id: number
  actor_name: string | null
  category: string
  action: string
  target_type: string | null
  server_id: number | null
  status: string
  summary: string | null
  detail: any
  ip_address: string | null
  created_at: string | null
}

// ─── Constants ────────────────────────────────────────────────────────────────

const TYPE_META: Record<string, { icon: string; color: string; key?: TranslationKey }> = {
  snapshot: { icon: '', color: 'text-cyan-300' },
  agent: { icon: '', color: 'text-blue-300' },
  package: { icon: '', color: 'text-orange-300', key: 'audit_pkg' },
  update:   { icon: '', color: 'text-blue-300', key: 'audit_upd' },
}

function typeLabel(type: string, t: (k: TranslationKey) => string) {
  if (type === 'package') return t('audit_pkg')
  if (type === 'update') return t('audit_upd')
  if (type === 'snapshot') return 'Snapshot'
  if (type === 'agent') return 'Agent'
  return type
}

const STATUS_STYLE: Record<string, string> = {
  pending:  'bg-yellow-500/15 text-yellow-300 border-yellow-500/40',
  running:  'bg-blue-500/15 text-blue-300 border-blue-500/40',
  active:   'bg-green-500/15 text-green-300 border-green-500/40',
  executed: 'bg-green-500/15 text-green-300 border-green-500/40',
  success:  'bg-green-500/15 text-green-300 border-green-500/40',
  approved: 'bg-teal-500/15 text-teal-300 border-teal-500/40',
  failed:   'bg-red-500/15 text-red-300 border-red-500/40',
  rejected: 'bg-orange-500/15 text-orange-300 border-orange-500/40',
  deleted:  'bg-slate-500/15 text-slate-400 border-slate-500/40',
  blocked:  'bg-red-500/15 text-red-300 border-red-500/40',
}

const STATUS_KEYS: Record<string, TranslationKey> = {
  pending: 'audit_st_pending', running: 'audit_st_running', active: 'audit_st_active',
  executed: 'audit_st_executed', success: 'audit_st_success', approved: 'audit_st_approved',
  failed: 'audit_st_failed', rejected: 'audit_st_rejected', deleted: 'audit_st_deleted', blocked: 'audit_st_blocked',
}

const CAT_KEYS: Record<string, TranslationKey> = {
  auth: 'audit_cat_auth', system_update: 'audit_cat_sysupd',
  package: 'audit_cat_pkg', knowledge: 'audit_cat_kb', applications: 'audit_cat_apps',
  modules: 'audit_cat_mods', settings: 'audit_cat_set',
}

const CAT_FALLBACK: Record<string, string> = {
  agent: 'Agent', ssh: 'SSH', rca: 'RCA', snapshot: 'Snapshot', nlq: 'NLQ',
}

const CAT_COLOR: Record<string, string> = {
  auth: 'text-sky-300', agent: 'text-blue-300', system_update: 'text-blue-300',
  ssh: 'text-emerald-300', rca: 'text-cyan-300', snapshot: 'text-pink-300', package: 'text-orange-300',
  knowledge: 'text-pink-300', applications: 'text-sky-300',
  modules: 'text-amber-300', settings: 'text-slate-300', nlq: 'text-teal-300',
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function catLabel(cat: string, t: (k: TranslationKey) => string) {
  const key = CAT_KEYS[cat]
  if (key) return t(key)
  return CAT_FALLBACK[cat] || cat
}

function statusLabel(status: string, t: (k: TranslationKey) => string) {
  const key = STATUS_KEYS[status]
  return key ? t(key) : status
}

const fmt = (s: string | null | undefined, loc: string) =>
  s ? new Date(s).toLocaleString(loc, { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'

const StatusBadge = ({ status }: { status: string }) => {
  const t = useT()
  return (
  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${STATUS_STYLE[status] || 'bg-white/[0.04] text-slate-300 border-white/[0.08]'}`}>
    {status === 'pending' && <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />}
    {status === 'running' && <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />}
    {statusLabel(status, t)}
  </span>
  )
}

// ─── Task Card ────────────────────────────────────────────────────────────────

const TaskCard = ({ task, onRefresh }: { task: Task; onRefresh: () => void }) => {
  const t = useT()
  const { locale } = useLocale()
  const dateLoc = locale === 'en' ? 'en-GB' : 'tr-TR'
  const [expanded, setExpanded] = useState(false)
  const meta = TYPE_META[task.type] || { icon: '', color: 'text-slate-300' }
  const isPending = task.status === 'pending' || task.status === 'running'

  return (
    <div
      className={`rounded-xl border transition-all ${
        isPending
          ? 'border-yellow-500/30 bg-yellow-500/5'
          : task.status === 'failed'
          ? 'border-red-500/25 bg-red-500/5'
          : task.status === 'active' || task.status === 'executed' || task.status === 'success'
          ? 'border-green-500/20 bg-green-500/5'
          : 'border-white/[0.06] bg-cyber-card'
      }`}
    >
      <div
        className="flex items-start gap-3 px-4 py-3 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        {/* Icon + spinner */}
        <div className="relative mt-0.5 flex-shrink-0">
          <span className="text-lg">{meta.icon}</span>
          {isPending && (
            <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-yellow-400 animate-ping" />
          )}
        </div>

        {/* Main content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-xs font-semibold uppercase tracking-wider ${meta.color}`}>{typeLabel(task.type, t)}</span>
            <StatusBadge status={task.status} />
            {task.platform && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.06] text-slate-400 border border-white/[0.06]">
                {task.platform.toUpperCase()}
              </span>
            )}
            {task.risk_level && task.risk_level !== 'read_only' && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded border ${task.risk_level === 'mutating' ? 'bg-orange-500/10 text-orange-300 border-orange-500/30' : 'bg-red-500/10 text-red-300 border-red-500/30'}`}>
                {task.risk_level}
              </span>
            )}
          </div>
          <div className="text-sm text-slate-200 mt-0.5 font-medium truncate">{task.title}</div>
          {task.preview && (
            <div className="text-xs text-slate-400 font-mono truncate mt-0.5">{task.preview}</div>
          )}
          <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-500">
            <span>{task.subtitle}</span>
            <span>·</span>
            <span title={fmt(task.created_at, dateLoc)}>{t('audit_ago', { age: task.age })}</span>
            {task.source && task.source !== 'manual' && <><span>·</span><span>{task.source}</span></>}
            {task.retention && <><span>·</span><span>{task.retention}</span></>}
          </div>
        </div>

        {/* Expand arrow */}
        <span className="text-slate-600 text-xs mt-1">{expanded ? '▲' : '▼'}</span>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-3 border-t border-white/[0.05] pt-3 space-y-2">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
            <div><span className="text-slate-500">{t('audit_created')} </span><span className="text-slate-300">{fmt(task.created_at, dateLoc)}</span></div>
            {task.decided_at && <div><span className="text-slate-500">{t('audit_decision')} </span><span className="text-slate-300">{fmt(task.decided_at, dateLoc)}</span></div>}
            {task.executed_at && <div><span className="text-slate-500">{t('audit_ran')} </span><span className="text-slate-300">{fmt(task.executed_at, dateLoc)}</span></div>}
            {task.decided_by && <div><span className="text-slate-500">{t('audit_decided_by')} </span><span className="text-slate-300">{task.decided_by}</span></div>}
            {task.snapshot_id && <div><span className="text-slate-500">{t('audit_snap_id')} </span><span className="text-slate-300 font-mono">{task.snapshot_id}</span></div>}
            {task.step && <div><span className="text-slate-500">{t('audit_step')} </span><span className="text-slate-300">{task.step}</span></div>}
          </div>
          {task.error_message && (
            <div className="bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2 text-xs text-red-300">
              <span className="font-medium">{t('audit_err')} </span>{task.error_message}
            </div>
          )}
          {/* Snapshot sil butonu */}
          {task.type === 'snapshot' && task.status !== 'deleted' && task.raw_id && (
            <button
              onClick={async (e) => {
                e.stopPropagation()
                if (!confirm(t('audit_del_confirm'))) return
                await fetch(`${API_BASE_URL}/snapshots/${task.raw_id}`, { method: 'DELETE' })
                onRefresh()
              }}
              className="text-xs text-red-400 hover:text-red-300 px-2 py-1 rounded hover:bg-red-500/10 border border-red-500/20"
            >
              {t('audit_del_snap')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Tasks Panel ──────────────────────────────────────────────────────────────

const TasksPanel = () => {
  const t = useT()
  const [typeFilter, setTypeFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [hours, setHours] = useState(24)
  const [autoRefresh, setAutoRefresh] = useState(true)

  const { data, refetch, isFetching } = useQuery<{ summary: TaskSummary; tasks: Task[]; hours: number }>({
    queryKey: ['tasks', typeFilter, statusFilter, hours],
    queryFn: async () => {
      const p = new URLSearchParams({ hours: String(hours) })
      if (typeFilter) p.set('type', typeFilter)
      const r = await fetch(`${API_BASE_URL}/tasks/?${p}`)
      if (!r.ok) return { summary: { total: 0, pending: 0, running: 0, failed: 0, active: 0 }, tasks: [], hours }
      return r.json()
    },
    refetchInterval: autoRefresh ? 10_000 : false,
  })

  const tasks = (data?.tasks || []).filter(task => !statusFilter || task.status === statusFilter)
  const summary = data?.summary || { total: 0, pending: 0, running: 0, failed: 0, active: 0 }

  return (
    <div className="space-y-4">
      {/* Özet kartları */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { id: 'all', label: t('total'), value: summary.total, color: 'text-white', bg: 'bg-cyber-card', border: 'border-white/[0.06]' },
          { id: 'pending', label: t('audit_waiting'), value: summary.pending + summary.running, color: 'text-yellow-300', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30' },
          { id: 'failed', label: t('audit_st_failed'), value: summary.failed, color: 'text-red-300', bg: 'bg-red-500/10', border: 'border-red-500/30' },
          { id: 'active', label: t('audit_completed'), value: summary.active, color: 'text-green-300', bg: 'bg-green-500/10', border: 'border-green-500/30' },
        ].map(c => (
          <button
            key={c.id}
            onClick={() => setStatusFilter(
              c.id === 'pending' ? (statusFilter === 'pending' ? '' : 'pending')
              : c.id === 'failed' ? (statusFilter === 'failed' ? '' : 'failed')
              : c.id === 'active' ? (statusFilter === 'active' ? '' : 'active')
              : ''
            )}
            className={`${c.bg} border ${c.border} rounded-[10px] p-4 text-left hover:brightness-110 transition-all`}
          >
            <div className={`text-2xl font-bold ${c.color}`}>{c.value}</div>
            <div className="text-xs text-slate-400 mt-0.5">{c.label}</div>
          </button>
        ))}
      </div>

      {/* Filtre bar */}
      <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] px-3 py-2.5 flex flex-wrap gap-2 items-center">
        <div className="flex rounded-lg overflow-hidden border border-white/[0.08]">
          {[['', t('filter_all')], ['snapshot', 'Snapshot'], ['agent', 'Agent'], ['package', t('audit_pkg')], ['update', t('audit_upd')]].map(([v, l]) => (
            <button
              key={v}
              onClick={() => setTypeFilter(v)}
              className={`px-3 py-1.5 text-xs transition-colors ${typeFilter === v ? 'bg-blue-600 text-white' : 'bg-cyber-card text-slate-400 hover:text-slate-200'}`}
            >{l}</button>
          ))}
        </div>
        <div className="flex rounded-lg overflow-hidden border border-white/[0.08] ml-auto">
          {[['1', t('audit_1h')], ['6', t('audit_6h')], ['24', t('audit_24h')], ['72', t('audit_3d')], ['168', t('audit_7d')]].map(([v, l]) => (
            <button
              key={v}
              onClick={() => setHours(Number(v))}
              className={`px-2.5 py-1.5 text-xs transition-colors ${hours === Number(v) ? 'bg-white/[0.10] text-white' : 'bg-cyber-card text-slate-400 hover:text-slate-200'}`}
            >{l}</button>
          ))}
        </div>
        <button
          onClick={() => setAutoRefresh(!autoRefresh)}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg border transition-colors ${autoRefresh ? 'bg-green-500/15 text-green-300 border-green-500/30' : 'bg-white/[0.05] text-slate-400 border-white/[0.07]'}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${autoRefresh ? 'bg-green-400 animate-pulse' : 'bg-slate-500'}`} />
          {autoRefresh ? t('lm_live') : t('audit_stopped')}
        </button>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="px-2.5 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded-lg disabled:opacity-50"
        >
          {isFetching ? '...' : t('audit_refresh_btn')}
        </button>
      </div>

      {/* Görev listesi */}
      {tasks.length === 0 ? (
        <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-12 text-center text-slate-500">
          <div className="text-2xl font-bold text-green-400 mb-3">✓</div>
          {t('audit_no_tasks', { n: hours })}
        </div>
      ) : (
        <div className="space-y-2">
          {/* Bekleyen görevler */}
          {tasks.filter(task => task.status === 'pending' || task.status === 'running').length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs font-semibold text-yellow-400 uppercase tracking-wider px-1">
                <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
                {t('audit_active_tasks', { n: tasks.filter(task => task.status === 'pending' || task.status === 'running').length })}
              </div>
              {tasks.filter(task => task.status === 'pending' || task.status === 'running').map(task => (
                <TaskCard key={task.id} task={task} onRefresh={refetch} />
              ))}
            </div>
          )}

          {/* Başarısız */}
          {tasks.filter(task => task.status === 'failed').length > 0 && (
            <div className="space-y-2 mt-4">
              <div className="flex items-center gap-2 text-xs font-semibold text-red-400 uppercase tracking-wider px-1">
                {t('audit_failed_n', { n: tasks.filter(task => task.status === 'failed').length })}
              </div>
              {tasks.filter(task => task.status === 'failed').map(task => (
                <TaskCard key={task.id} task={task} onRefresh={refetch} />
              ))}
            </div>
          )}

          {/* Tamamlanan */}
          {tasks.filter(task => !['pending', 'running', 'failed'].includes(task.status)).length > 0 && (
            <div className="space-y-2 mt-4">
              <div className="flex items-center gap-2 text-xs font-semibold text-slate-400 uppercase tracking-wider px-1">
                ✓ {t('audit_done_n', { n: tasks.filter(task => !['pending', 'running', 'failed'].includes(task.status)).length })}
              </div>
              {tasks.filter(task => !['pending', 'running', 'failed'].includes(task.status)).map(task => (
                <TaskCard key={task.id} task={task} onRefresh={refetch} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Audit Log Panel ─────────────────────────────────────────────────────────

const AuditPanel = () => {
  const t = useT()
  const { locale } = useLocale()
  const dateLoc = locale === 'en' ? 'en-GB' : 'tr-TR'
  const [category, setCategory] = useState('')
  const [status, setStatus]     = useState('')
  const [actor, setActor]       = useState('')
  const [q, setQ]               = useState('')
  const [days, setDays]         = useState('30')
  const [offset, setOffset]     = useState(0)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const limit = 100

  const { data, refetch, isFetching, isError, error } = useQuery<{ total: number; logs: AuditRow[] }>({
    queryKey: ['audit', category, status, actor, q, days, offset],
    queryFn: async () => {
      const p = new URLSearchParams()
      if (category) p.set('category', category)
      if (status) p.set('status', status)
      if (actor) p.set('actor', actor)
      if (q) p.set('q', q)
      if (days) p.set('days', days)
      p.set('limit', String(limit))
      p.set('offset', String(offset))
      const r = await fetch(`${API_BASE_URL}/audit/?${p}`)
      if (!r.ok) {
        const detail = await r.text().catch(() => '')
        throw new Error(r.status === 403 ? t('audit_forbidden') : `${t('audit_api_err', { status: r.status })}${detail ? `: ${detail.slice(0, 120)}` : ''}`)
      }
      setFetchError(null)
      return r.json()
    },
    refetchInterval: 30000,
    retry: 1,
  })

  // query error → kullanıcıya göster
  useEffect(() => {
    if (isError && error) setFetchError((error as Error).message || t('audit_load_fail'))
  }, [isError, error])

  const { data: stats } = useQuery<any>({
    queryKey: ['audit-stats', days],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/audit/stats?days=${days || 7}`)
      return r.ok ? r.json() : null
    },
  })

  const rows = data?.logs || []
  const total = data?.total || 0

  return (
    <div className="space-y-4">
      {fetchError && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200">
          {t('audit_load_fail_detail', { msg: fetchError })}
        </div>
      )}
      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-4">
            <div className="text-2xl font-bold text-white">{stats.total}</div>
            <div className="text-xs text-slate-400 mt-0.5">{t('audit_records_d', { n: stats.days })}</div>
          </div>
          <div className="bg-green-500/10 border border-green-500/25 rounded-xl p-4">
            <div className="text-2xl font-bold text-green-300">{stats.by_status?.success || 0}</div>
            <div className="text-xs text-slate-400 mt-0.5">{t('audit_st_success')}</div>
          </div>
          <div className="bg-red-500/10 border border-red-500/25 rounded-xl p-4">
            <div className="text-2xl font-bold text-red-300">
              {(stats.by_status?.failure || 0) + (stats.by_status?.blocked || 0) + (stats.by_status?.rejected || 0)}
            </div>
            <div className="text-xs text-slate-400 mt-0.5">{t('audit_fail_blocked')}</div>
          </div>
          <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-4">
            <div className="text-sm font-bold text-white truncate">{Object.keys(stats.top_actors || {})[0] || '—'}</div>
            <div className="text-xs text-slate-400 mt-0.5">{t('audit_top_actor')}</div>
          </div>
        </div>
      )}

      {/* Filtreler */}
      <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-3 flex flex-wrap gap-2 items-center">
        <select value={category} onChange={e => { setOffset(0); setCategory(e.target.value) }}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200">
          <option value="">{t('audit_all_cats')}</option>
          {['auth', 'agent', 'system_update', 'ssh', 'rca', 'snapshot', 'package', 'knowledge', 'applications', 'modules', 'settings', 'nlq'].map(k => (
            <option key={k} value={k}>{catLabel(k, t)}</option>
          ))}
        </select>
        <select value={status} onChange={e => { setOffset(0); setStatus(e.target.value) }}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200">
          <option value="">{t('audit_all_status')}</option>
          <option value="success">{t('audit_st_success')}</option>
          <option value="failure">{t('audit_st_failed')}</option>
          <option value="rejected">{t('audit_st_rejected')}</option>
          <option value="blocked">{t('audit_st_blocked')}</option>
          <option value="pending">{t('audit_st_pending')}</option>
        </select>
        <select value={days} onChange={e => { setOffset(0); setDays(e.target.value) }}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200">
          <option value="1">{t('audit_last_1d')}</option>
          <option value="7">{t('audit_last_7d')}</option>
          <option value="30">{t('audit_last_30d')}</option>
          <option value="">{t('filter_all')}</option>
        </select>
        <input value={actor} onChange={e => { setOffset(0); setActor(e.target.value) }}
          placeholder={t('audit_user_ph')}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200 w-32" />
        <input value={q} onChange={e => { setOffset(0); setQ(e.target.value) }}
          placeholder={t('audit_sum_ph')}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200 flex-1 min-w-[120px]" />
        <button onClick={() => refetch()} disabled={isFetching}
          className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg disabled:opacity-50">
          {isFetching ? '...' : t('audit_refresh_btn')}
        </button>
      </div>

      {/* Tablo */}
      <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-cyber-deep/60 text-slate-400 text-xs">
              <tr>
                <th className="text-left px-3 py-2.5 font-medium">{t('audit_col_time')}</th>
                <th className="text-left px-3 py-2.5 font-medium">{t('audit_col_user')}</th>
                <th className="text-left px-3 py-2.5 font-medium">{t('audit_col_cat')}</th>
                <th className="text-left px-3 py-2.5 font-medium">{t('audit_col_act')}</th>
                <th className="text-left px-3 py-2.5 font-medium">{t('audit_col_sum')}</th>
                <th className="text-left px-3 py-2.5 font-medium">{t('audit_col_st')}</th>
                <th className="text-left px-3 py-2.5 font-medium">IP</th>
                <th className="px-3 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {rows.map(r => (
                <React.Fragment key={r.id}>
                  <tr
                    className="hover:bg-white/[0.03] cursor-pointer"
                    onClick={() => setExpanded(expanded === r.id ? null : r.id)}
                  >
                    <td className="px-3 py-2 text-slate-400 whitespace-nowrap text-xs">{fmt(r.created_at, dateLoc)}</td>
                    <td className="px-3 py-2 text-slate-200 whitespace-nowrap text-xs">{r.actor_name || '—'}</td>
                    <td className={`px-3 py-2 whitespace-nowrap text-xs font-medium ${CAT_COLOR[r.category] || 'text-slate-300'}`}>
                      {catLabel(r.category, t)}
                    </td>
                    <td className="px-3 py-2 text-slate-500 font-mono text-[11px] whitespace-nowrap">{r.action}</td>
                    <td className="px-3 py-2 text-slate-300 text-xs max-w-xs truncate" title={r.summary || ''}>{r.summary || '—'}</td>
                    <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                    <td className="px-3 py-2 text-slate-500 font-mono text-[11px]">{r.ip_address || '—'}</td>
                    <td className="px-3 py-2 text-slate-600 text-xs">{expanded === r.id ? '▲' : '▼'}</td>
                  </tr>
                  {expanded === r.id && r.detail && (
                    <tr className="bg-cyber-deep/60">
                      <td colSpan={8} className="px-4 py-3">
                        <pre className="text-xs text-slate-400 whitespace-pre-wrap font-mono bg-slate-900/60 rounded-lg p-3 max-h-48 overflow-y-auto">
                          {JSON.stringify(r.detail, null, 2)}
                        </pre>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
              {!isFetching && rows.length === 0 && (
                <tr><td colSpan={8} className="px-3 py-10 text-center text-slate-500">{t('audit_none')}</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Sayfalama */}
        <div className="flex items-center justify-between px-3 py-2.5 border-t border-white/[0.05] text-xs text-slate-400">
          <span>{total > 0
            ? t('audit_range', { total: total.toLocaleString(dateLoc), from: offset + 1, to: Math.min(offset + limit, total).toLocaleString(dateLoc) })
            : t('audit_total_n', { n: total.toLocaleString(dateLoc) })}</span>
          <div className="flex gap-2">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}
              className="px-2.5 py-1 rounded-lg bg-white/[0.07] disabled:opacity-40 hover:bg-white/[0.10] text-slate-200">← {t('page_prev')}</button>
            <button disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}
              className="px-2.5 py-1 rounded-lg bg-white/[0.07] disabled:opacity-40 hover:bg-white/[0.10] text-slate-200">{t('page_next')} →</button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

const ActivityCenter: React.FC = () => {
  const t = useT()
  const [tab, setTab] = useState<'tasks' | 'audit' | 'level1'>('audit')

  const { data: badge } = useQuery<{ count: number; snap: number; agent: number }>({
    queryKey: ['active-task-count'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/tasks/active-count`)
      return r.ok ? r.json() : { count: 0, snap: 0, agent: 0 }
    },
    refetchInterval: 15_000,
  })

  return (
    <div className="space-y-4">
      {/* Başlık */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white">{t('nav_audit_log')}</h1>
        <div className="text-xs text-slate-500">
          {badge && badge.count > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-yellow-500/15 text-yellow-300 border border-yellow-500/30">
              <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
              {t('audit_active_n', { n: badge.count })}
            </span>
          )}
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-white/[0.07]">
        <button
          onClick={() => setTab('audit')}
          className={`flex items-center gap-2 px-5 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            tab === 'audit'
              ? 'border-blue-500 text-white'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          {t('nav_audit_log')}
        </button>
        <button
          onClick={() => setTab('level1')}
          className={`flex items-center gap-2 px-5 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            tab === 'level1'
              ? 'border-blue-500 text-white'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          {t('audit_tab_l1')}
        </button>
        <button
          onClick={() => setTab('tasks')}
          className={`flex items-center gap-2 px-5 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            tab === 'tasks'
              ? 'border-blue-500 text-white'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          {t('audit_tab_tasks')}
          {badge && badge.count > 0 && (
            <span className="px-1.5 py-0.5 text-[10px] rounded-full bg-yellow-500 text-black font-bold">
              {badge.count}
            </span>
          )}
        </button>
      </div>

      {tab === 'audit' && <AuditPanel />}
      {tab === 'level1' && <Level1AuditEmbed />}
      {tab === 'tasks' && <TasksPanel />}
    </div>
  )
}

function Level1AuditEmbed() {
  const t = useT()
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const { ensureDroptSession } = await import('./level1/Level1Shell')
        await ensureDroptSession()
        if (!cancelled) setReady(true)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      }
    })()
    return () => { cancelled = true }
  }, [])

  return (
    <div className="rounded-xl border border-white/[0.06] overflow-hidden bg-cyber-card level1-dropt-root">
      <div className="px-4 py-2 border-b border-white/[0.06] text-xs text-slate-400">
        {t('audit_l1_src')}{' '}
        <a href="/level1/audit" className="text-blue-400 hover:underline">{t('audit_l1_link')}</a>
      </div>
      {error && <div className="p-4 text-red-400 text-sm whitespace-pre-wrap">{error}</div>}
      {!ready && !error && <div className="p-6 text-slate-400 text-sm">{t('audit_dropt_prep')}</div>}
      {ready && (
        <React.Suspense fallback={<div className="p-6 text-slate-400 text-sm">{t('loading')}</div>}>
          <Level1AuditContentLazy />
        </React.Suspense>
      )}
    </div>
  )
}

const Level1AuditContentLazy = lazyWithRetry(() =>
  import('./level1/Level1Audit').then((m) => ({ default: m.Level1AuditContent })),
)

export default ActivityCenter
