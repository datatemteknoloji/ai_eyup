import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

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

const TYPE_META: Record<string, { label: string; icon: string; color: string }> = {
  snapshot: { label: 'Snapshot', icon: '', color: 'text-cyan-300' },
  agent: { label: 'Agent', icon: '', color: 'text-blue-300' },
  package: { label: 'Paket', icon: '', color: 'text-orange-300' },
  update:   { label: 'Güncelleme', icon: '', color: 'text-blue-300' },
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

const STATUS_TR: Record<string, string> = {
  pending: 'Bekliyor', running: 'Çalışıyor', active: 'Tamamlandı',
  executed: 'Çalıştırıldı', success: 'Başarılı', approved: 'Onaylandı',
  failed: 'Başarısız', rejected: 'Reddedildi', deleted: 'Silindi', blocked: 'Engellendi',
}

const CAT_LABEL: Record<string, string> = {
  auth: 'Kimlik', agent: 'Agent', system_update: 'OS Güncelleme',
  ssh: 'SSH', rca: 'RCA', snapshot: 'Snapshot', package: 'Paket',
}

const CAT_COLOR: Record<string, string> = {
  auth: 'text-sky-300', agent: 'text-blue-300', system_update: 'text-blue-300',
  ssh: 'text-emerald-300', rca: 'text-cyan-300', snapshot: 'text-pink-300', package: 'text-orange-300',
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmt = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleString('tr-TR', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'

const StatusBadge = ({ status }: { status: string }) => (
  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${STATUS_STYLE[status] || 'bg-white/[0.04] text-slate-300 border-white/[0.08]'}`}>
    {status === 'pending' && <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />}
    {status === 'running' && <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />}
    {STATUS_TR[status] || status}
  </span>
)

// ─── Task Card ────────────────────────────────────────────────────────────────

const TaskCard = ({ task, onRefresh }: { task: Task; onRefresh: () => void }) => {
  const [expanded, setExpanded] = useState(false)
  const meta = TYPE_META[task.type] || { label: task.type, icon: '', color: 'text-slate-300' }
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
            <span className={`text-xs font-semibold uppercase tracking-wider ${meta.color}`}>{meta.label}</span>
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
            <span title={fmt(task.created_at)}>{task.age} önce</span>
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
            <div><span className="text-slate-500">Oluşturuldu: </span><span className="text-slate-300">{fmt(task.created_at)}</span></div>
            {task.decided_at && <div><span className="text-slate-500">Karar: </span><span className="text-slate-300">{fmt(task.decided_at)}</span></div>}
            {task.executed_at && <div><span className="text-slate-500">Çalıştı: </span><span className="text-slate-300">{fmt(task.executed_at)}</span></div>}
            {task.decided_by && <div><span className="text-slate-500">Karar veren: </span><span className="text-slate-300">{task.decided_by}</span></div>}
            {task.snapshot_id && <div><span className="text-slate-500">Snap ID: </span><span className="text-slate-300 font-mono">{task.snapshot_id}</span></div>}
            {task.step && <div><span className="text-slate-500">Adım: </span><span className="text-slate-300">{task.step}</span></div>}
          </div>
          {task.error_message && (
            <div className="bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2 text-xs text-red-300">
              <span className="font-medium">Hata: </span>{task.error_message}
            </div>
          )}
          {/* Snapshot sil butonu */}
          {task.type === 'snapshot' && task.status !== 'deleted' && task.raw_id && (
            <button
              onClick={async (e) => {
                e.stopPropagation()
                if (!confirm('Snapshot silinsin mi?')) return
                await fetch(`${API_BASE_URL}/snapshots/${task.raw_id}`, { method: 'DELETE' })
                onRefresh()
              }}
              className="text-xs text-red-400 hover:text-red-300 px-2 py-1 rounded hover:bg-red-500/10 border border-red-500/20"
            >
              Snapshot'u Sil
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Tasks Panel ──────────────────────────────────────────────────────────────

const TasksPanel = () => {
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
    refetchInterval: autoRefresh ? 5000 : false,
  })

  const tasks = (data?.tasks || []).filter(t => !statusFilter || t.status === statusFilter)
  const summary = data?.summary || { total: 0, pending: 0, running: 0, failed: 0, active: 0 }

  return (
    <div className="space-y-4">
      {/* Özet kartları */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Toplam', value: summary.total, color: 'text-white', bg: 'bg-cyber-card', border: 'border-white/[0.06]' },
          { label: 'Bekliyor', value: summary.pending + summary.running, color: 'text-yellow-300', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30' },
          { label: 'Başarısız', value: summary.failed, color: 'text-red-300', bg: 'bg-red-500/10', border: 'border-red-500/30' },
          { label: 'Tamamlandı', value: summary.active, color: 'text-green-300', bg: 'bg-green-500/10', border: 'border-green-500/30' },
        ].map(c => (
          <button
            key={c.label}
            onClick={() => setStatusFilter(
              c.label === 'Bekliyor' ? (statusFilter === 'pending' ? '' : 'pending')
              : c.label === 'Başarısız' ? (statusFilter === 'failed' ? '' : 'failed')
              : c.label === 'Tamamlandı' ? (statusFilter === 'active' ? '' : 'active')
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
          {[['', 'Tümü'], ['snapshot', 'Snapshot'], ['agent', 'Agent'], ['package', 'Paket'], ['update', 'Güncelleme']].map(([v, l]) => (
            <button
              key={v}
              onClick={() => setTypeFilter(v)}
              className={`px-3 py-1.5 text-xs transition-colors ${typeFilter === v ? 'bg-blue-600 text-white' : 'bg-cyber-card text-slate-400 hover:text-slate-200'}`}
            >{l}</button>
          ))}
        </div>
        <div className="flex rounded-lg overflow-hidden border border-white/[0.08] ml-auto">
          {[['1', '1s'], ['6', '6s'], ['24', '24s'], ['72', '3g'], ['168', '7g']].map(([v, l]) => (
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
          {autoRefresh ? 'Canlı' : 'Durdur'}
        </button>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="px-2.5 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded-lg disabled:opacity-50"
        >
          {isFetching ? '...' : '↺ Yenile'}
        </button>
      </div>

      {/* Görev listesi */}
      {tasks.length === 0 ? (
        <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-12 text-center text-slate-500">
          <div className="text-2xl font-bold text-green-400 mb-3">✓</div>
          Son {hours} saatte görev bulunamadı
        </div>
      ) : (
        <div className="space-y-2">
          {/* Bekleyen görevler */}
          {tasks.filter(t => t.status === 'pending' || t.status === 'running').length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs font-semibold text-yellow-400 uppercase tracking-wider px-1">
                <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
                Aktif Görevler ({tasks.filter(t => t.status === 'pending' || t.status === 'running').length})
              </div>
              {tasks.filter(t => t.status === 'pending' || t.status === 'running').map(t => (
                <TaskCard key={t.id} task={t} onRefresh={refetch} />
              ))}
            </div>
          )}

          {/* Başarısız */}
          {tasks.filter(t => t.status === 'failed').length > 0 && (
            <div className="space-y-2 mt-4">
              <div className="flex items-center gap-2 text-xs font-semibold text-red-400 uppercase tracking-wider px-1">
                Başarısız ({tasks.filter(t => t.status === 'failed').length})
              </div>
              {tasks.filter(t => t.status === 'failed').map(t => (
                <TaskCard key={t.id} task={t} onRefresh={refetch} />
              ))}
            </div>
          )}

          {/* Tamamlanan */}
          {tasks.filter(t => !['pending', 'running', 'failed'].includes(t.status)).length > 0 && (
            <div className="space-y-2 mt-4">
              <div className="flex items-center gap-2 text-xs font-semibold text-slate-400 uppercase tracking-wider px-1">
                ✓ Tamamlanan ({tasks.filter(t => !['pending', 'running', 'failed'].includes(t.status)).length})
              </div>
              {tasks.filter(t => !['pending', 'running', 'failed'].includes(t.status)).map(t => (
                <TaskCard key={t.id} task={t} onRefresh={refetch} />
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
  const [category, setCategory] = useState('')
  const [status, setStatus]     = useState('')
  const [actor, setActor]       = useState('')
  const [q, setQ]               = useState('')
  const [days, setDays]         = useState('7')
  const [offset, setOffset]     = useState(0)
  const [expanded, setExpanded] = useState<number | null>(null)
  const limit = 100

  const { data, refetch, isFetching } = useQuery<{ total: number; logs: AuditRow[] }>({
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
      if (!r.ok) return { total: 0, logs: [] }
      return r.json()
    },
    refetchInterval: 30000,
  })

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
      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-4">
            <div className="text-2xl font-bold text-white">{stats.total}</div>
            <div className="text-xs text-slate-400 mt-0.5">Toplam kayıt ({stats.days}g)</div>
          </div>
          <div className="bg-green-500/10 border border-green-500/25 rounded-xl p-4">
            <div className="text-2xl font-bold text-green-300">{stats.by_status?.success || 0}</div>
            <div className="text-xs text-slate-400 mt-0.5">Başarılı</div>
          </div>
          <div className="bg-red-500/10 border border-red-500/25 rounded-xl p-4">
            <div className="text-2xl font-bold text-red-300">
              {(stats.by_status?.failure || 0) + (stats.by_status?.blocked || 0) + (stats.by_status?.rejected || 0)}
            </div>
            <div className="text-xs text-slate-400 mt-0.5">Başarısız / Engellendi</div>
          </div>
          <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-4">
            <div className="text-sm font-bold text-white truncate">{Object.keys(stats.top_actors || {})[0] || '—'}</div>
            <div className="text-xs text-slate-400 mt-0.5">En aktif kullanıcı</div>
          </div>
        </div>
      )}

      {/* Filtreler */}
      <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] p-3 flex flex-wrap gap-2 items-center">
        <select value={category} onChange={e => { setOffset(0); setCategory(e.target.value) }}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200">
          <option value="">Tüm kategoriler</option>
          {Object.entries(CAT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={status} onChange={e => { setOffset(0); setStatus(e.target.value) }}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200">
          <option value="">Tüm durumlar</option>
          <option value="success">Başarılı</option>
          <option value="failure">Başarısız</option>
          <option value="rejected">Reddedildi</option>
          <option value="blocked">Engellendi</option>
          <option value="pending">Bekliyor</option>
        </select>
        <select value={days} onChange={e => { setOffset(0); setDays(e.target.value) }}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200">
          <option value="1">Son 1 gün</option>
          <option value="7">Son 7 gün</option>
          <option value="30">Son 30 gün</option>
          <option value="">Tümü</option>
        </select>
        <input value={actor} onChange={e => { setOffset(0); setActor(e.target.value) }}
          placeholder="Kullanıcı..."
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200 w-32" />
        <input value={q} onChange={e => { setOffset(0); setQ(e.target.value) }}
          placeholder="Özet ara..."
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-slate-200 flex-1 min-w-[120px]" />
        <button onClick={() => refetch()} disabled={isFetching}
          className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg disabled:opacity-50">
          {isFetching ? '...' : '↺ Yenile'}
        </button>
      </div>

      {/* Tablo */}
      <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-cyber-deep/60 text-slate-400 text-xs">
              <tr>
                <th className="text-left px-3 py-2.5 font-medium">Zaman</th>
                <th className="text-left px-3 py-2.5 font-medium">Kullanıcı</th>
                <th className="text-left px-3 py-2.5 font-medium">Kategori</th>
                <th className="text-left px-3 py-2.5 font-medium">Eylem</th>
                <th className="text-left px-3 py-2.5 font-medium">Özet</th>
                <th className="text-left px-3 py-2.5 font-medium">Durum</th>
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
                    <td className="px-3 py-2 text-slate-400 whitespace-nowrap text-xs">{fmt(r.created_at)}</td>
                    <td className="px-3 py-2 text-slate-200 whitespace-nowrap text-xs">{r.actor_name || '—'}</td>
                    <td className={`px-3 py-2 whitespace-nowrap text-xs font-medium ${CAT_COLOR[r.category] || 'text-slate-300'}`}>
                      {CAT_LABEL[r.category] || r.category}
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
                <tr><td colSpan={8} className="px-3 py-10 text-center text-slate-500">Kayıt bulunamadı</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Sayfalama */}
        <div className="flex items-center justify-between px-3 py-2.5 border-t border-white/[0.05] text-xs text-slate-400">
          <span>{total} kayıt{total > 0 ? ` · ${offset + 1}–${Math.min(offset + limit, total)}` : ''}</span>
          <div className="flex gap-2">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}
              className="px-2.5 py-1 rounded-lg bg-white/[0.07] disabled:opacity-40 hover:bg-white/[0.10] text-slate-200">← Önceki</button>
            <button disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}
              className="px-2.5 py-1 rounded-lg bg-white/[0.07] disabled:opacity-40 hover:bg-white/[0.10] text-slate-200">Sonraki →</button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

const ActivityCenter: React.FC = () => {
  const [tab, setTab] = useState<'tasks' | 'audit'>('tasks')

  const { data: badge } = useQuery<{ count: number; snap: number; agent: number }>({
    queryKey: ['active-task-count'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/tasks/active-count`)
      return r.ok ? r.json() : { count: 0, snap: 0, agent: 0 }
    },
    refetchInterval: 10000,
  })

  return (
    <div className="space-y-4">
      {/* Başlık */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white">Aktivite Merkezi</h1>
        <div className="text-xs text-slate-500">
          {badge && badge.count > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-yellow-500/15 text-yellow-300 border border-yellow-500/30">
              <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
              {badge.count} aktif görev
            </span>
          )}
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-white/[0.07]">
        <button
          onClick={() => setTab('tasks')}
          className={`flex items-center gap-2 px-5 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            tab === 'tasks'
              ? 'border-blue-500 text-white'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          Görev İzleme
          {badge && badge.count > 0 && (
            <span className="px-1.5 py-0.5 text-[10px] rounded-full bg-yellow-500 text-black font-bold">
              {badge.count}
            </span>
          )}
        </button>
        <button
          onClick={() => setTab('audit')}
          className={`flex items-center gap-2 px-5 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            tab === 'audit'
              ? 'border-blue-500 text-white'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          Audit Log
        </button>
      </div>

      {tab === 'tasks' ? <TasksPanel /> : <AuditPanel />}
    </div>
  )
}

export default ActivityCenter
