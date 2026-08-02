import React, { useState, useEffect, useCallback } from 'react'
import {
  AlertTriangle, CheckCircle2, XCircle, Lock, Zap, RefreshCw, Lightbulb,
  ClipboardList, Shield, Camera, Globe, Settings as SettingsIcon,
} from 'lucide-react'

// ─── Types ────────────────────────────────────────────────────────────────────
interface ServerItem {
  id: number; name: string; ip: string
  os_type: string|null; os_release_id: string; os_version_id: string
  os_version: string; kernel_version: string; status: string
  has_os_info: boolean; reboot_required?: boolean
}

interface RepoSource {
  id: number; name: string; display_name: string; repo_type: string
  sync_status: string; os_version: string|null
}
interface Package {
  name: string; new_version?: string; version?: string
  is_security: boolean; is_kernel: boolean
}
interface UpdateJob {
  id: number; server_id: number; server_name: string; server_ip: string
  os_type: string; os_version: string
  status: 'pending'|'running'|'completed'|'failed'|'skipped'
  packages_to_update: Package[]; packages_updated: Package[]
  reboot_required: boolean; log: string|null
  snapshot?: { status: string; snapshot_name: string; error_message?: string|null }
  started_at: string|null; completed_at: string|null
}
interface UpdatePlan {
  id: number; name: string; update_type: string; status: string
  total_servers: number; completed_servers: number
  ai_analysis: string|null; ai_summary: string|null
  server_ids: number[]; created_at: string
  started_at: string|null; completed_at: string|null
  // Credential ve config bilgileri
  distro_filter?: string|null
  repo_id?: number|null
  has_override_creds?: boolean
  override_username?: string|null
  priv_method?: string
  custom_packages?: string[]
  snapshot_mode?: string
  snapshot_retention?: string
}

// ─── Constants ────────────────────────────────────────────────────────────────
const API = '/api/v1/updates'

const authHeaders = (): Record<string, string> => {
  const t = localStorage.getItem('auth_token')
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (t) h['Authorization'] = `Bearer ${t}`
  return h
}

const DISTRO_LIST = [
  { key: 'rhel',   label: 'Red Hat Enterprise Linux', short: 'RHEL',   icon: 'RH', color: 'border-red-500/60 bg-red-500/10',    match: ['rhel'] },
  { key: 'oel',    label: 'Oracle Enterprise Linux',  short: 'OEL',    icon: 'OE', color: 'border-orange-500/60 bg-orange-500/10', match: ['ol', 'oel'] },
  { key: 'rocky',  label: 'Rocky Linux',              short: 'Rocky',  icon: 'RK', color: 'border-green-500/60 bg-green-500/10',  match: ['rocky'] },
  { key: 'ubuntu', label: 'Ubuntu',                   short: 'Ubuntu', icon: 'UB', color: 'border-yellow-500/60 bg-yellow-500/10', match: ['ubuntu'] },
  { key: '',       label: 'Tüm Dağıtımlar',           short: 'Tümü',   icon: '', color: 'border-slate-500/60 bg-white/[0.07]/30',  match: [] },
]

const UPDATE_TYPES = [
  { key: 'security', label: 'Güvenlik',       desc: 'Yalnızca CVE & güvenlik yamaları',  icon: 'SEC', color: 'border-orange-500 bg-orange-500/10 text-orange-300' },
  { key: 'kernel',   label: 'Kernel',         desc: 'Linux çekirdeği güncellemesi',       icon: 'KRN', color: 'border-blue-500 bg-blue-500/10 text-blue-300' },
  { key: 'all',      label: 'Tüm Paketler',   desc: 'Sistemdeki tüm paketleri güncelle',  icon: 'ALL', color: 'border-blue-500   bg-blue-500/10   text-blue-300'   },
  { key: 'custom',   label: 'Seçili Paketler',desc: 'Listeden belirli paketleri seç',     icon: 'SEÇ', color: 'border-cyan-500   bg-cyan-500/10   text-cyan-300'    },
]

const STATUS_COLOR: Record<string, string> = {
  draft: 'text-slate-400', ai_analyzing: 'text-blue-400 animate-pulse', ai_done: 'text-cyan-400',
  running: 'text-blue-400 animate-pulse', completed: 'text-green-400',
  failed: 'text-red-400', partial: 'text-orange-400', pending: 'text-slate-400', skipped: 'text-slate-500',
}
const STATUS_LABEL: Record<string, string> = {
  draft: 'Taslak', ai_analyzing: 'AI Analiz...', ai_done: 'Hazır',
  running: 'Çalışıyor', completed: 'Tamamlandı', failed: 'Başarısız',
  partial: 'Kısmi', pending: 'Bekliyor', skipped: 'Atlandı',
}
const fmtDate = (s: string|null) => s ? new Date(s).toLocaleString('tr-TR') : '—'

// ─── Step bar ─────────────────────────────────────────────────────────────────
const STEP_NAMES = ['Distro', 'Sunucular', 'Yetkili Kullanıcı', 'Repo', 'Snapshot', 'Güncelleme Modu', 'AI Analiz', 'Onayla', 'İzle']

const SNAPSHOT_RETENTIONS = [
  { key: '1d', label: '1 Gün', desc: '24 saat sonra otomatik silinir' },
  { key: '1w', label: '1 Hafta', desc: '7 gün saklanır (önerilen)' },
  { key: '1m', label: '1 Ay', desc: '30 gün saklanır' },
  { key: 'indefinite', label: 'Süresiz', desc: 'Manuel silinene kadar kalır' },
]

const Steps = ({ current, maxReached, onGoTo, locked }: {
  current: number; maxReached: number; onGoTo: (step: number) => void; locked?: boolean
}) => (
  <div className="flex items-center gap-1 flex-1 flex-wrap">
    {STEP_NAMES.map((s, i) => {
      const stepNum   = i + 1
      const isDone    = stepNum < current
      const isCurrent = stepNum === current
      const isVisited = stepNum <= maxReached
      // Job çalışırken (locked) geri adımlara gidilemez
      const canClick  = isVisited && !isCurrent && !locked
      return (
        <React.Fragment key={i}>
          <button
            onClick={() => canClick && onGoTo(stepNum)}
            disabled={!canClick}
            title={locked && isDone ? 'İş devam ederken önceki adımlara geçilemez' : canClick ? `${s} adımına git` : undefined}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all ${
              isCurrent  ? 'bg-blue-600 text-white' :
              isDone && locked ? 'bg-green-700/20 text-green-600 cursor-not-allowed' :
              isDone     ? 'bg-green-700/40 text-green-300 hover:bg-green-700/60 cursor-pointer' :
              isVisited  ? 'bg-white/[0.05] text-slate-300 hover:bg-white/[0.06] cursor-pointer' :
              'bg-cyber-card text-slate-500 cursor-default'
            }`}
          >
            {isDone ? '✓ ' : `${stepNum}. `}{s}
          </button>
          {i < STEP_NAMES.length-1 && (
            <div className={`flex-1 h-0.5 min-w-[6px] ${isDone ? 'bg-green-600' : isVisited ? 'bg-slate-600' : 'bg-white/[0.07]'}`} />
          )}
        </React.Fragment>
      )
    })}
  </div>
)

// ─── Server Selector ──────────────────────────────────────────────────────────
const ServerSelector = ({ servers, selected, onChange }: {
  servers: ServerItem[]; selected: number[]; onChange: (ids: number[]) => void
}) => {
  const [search, setSearch] = useState('')
  const filtered = servers.filter(s =>
    s.name.toLowerCase().includes(search.toLowerCase()) || s.ip.includes(search)
  )
  const toggle = (id: number) =>
    onChange(selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id])

  return (
    <div className="border border-white/[0.06] rounded-xl overflow-hidden">
      <div className="bg-cyber-card/80 px-3 py-2 flex gap-2 border-b border-white/[0.06] flex-wrap items-center">
        <input value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Sunucu veya IP ara..."
          className="flex-1 min-w-[160px] bg-white/[0.07] text-white text-sm px-3 py-1.5 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
        <button onClick={() => onChange(filtered.map(s => s.id))}
          className="text-xs text-blue-400 hover:text-blue-300 px-2.5 py-1.5 hover:bg-white/[0.06] rounded">Tümü</button>
        <button onClick={() => onChange(filtered.filter(s => s.status === 'ONLINE').map(s => s.id))}
          className="text-xs text-green-400 hover:text-green-300 px-2.5 py-1.5 hover:bg-white/[0.06] rounded">Aktifler</button>
        <button onClick={() => onChange([])}
          className="text-xs text-slate-400 hover:text-slate-300 px-2.5 py-1.5 hover:bg-white/[0.06] rounded">Temizle</button>
        <span className="text-xs text-slate-500 ml-auto">{selected.length} / {servers.length} seçili</span>
      </div>
      <div className="max-h-64 overflow-y-auto divide-y divide-white/[0.04]">
        {filtered.map(srv => (
          <label key={srv.id}
            className={`flex items-center gap-3 px-4 py-2.5 cursor-pointer transition-colors hover:bg-white/[0.03] ${selected.includes(srv.id) ? 'bg-blue-600/10' : ''}`}>
            <input type="checkbox" checked={selected.includes(srv.id)} onChange={() => toggle(srv.id)}
              className="accent-blue-500 w-4 h-4 flex-shrink-0" />
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${srv.status === 'ONLINE' ? 'bg-green-400' : 'bg-slate-500'}`} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <div className="text-sm font-medium text-white truncate">{srv.name}</div>
                {srv.reboot_required && (
                  <span className="flex items-center gap-1 text-[10px] bg-yellow-500/20 text-yellow-300 border border-yellow-500/30 px-1.5 py-0.5 rounded-md flex-shrink-0">
                    <AlertTriangle size={10} strokeWidth={2} /> Reboot
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 text-xs flex-wrap">
                <span className="text-slate-400 font-mono">{srv.ip}</span>
                {srv.os_release_id ? (
                  <span className="text-blue-400 font-medium">
                    {srv.os_release_id.toUpperCase()} {srv.os_version_id}
                  </span>
                ) : srv.os_version ? (
                  <span className="text-slate-300 truncate max-w-[200px]">{srv.os_version}</span>
                ) : (
                  <span className="flex items-center gap-1 text-yellow-500 text-[10px]">
                    <AlertTriangle size={10} strokeWidth={2} /> OS bilgisi yok
                  </span>
                )}
                {srv.kernel_version && (
                  <span className="flex items-center gap-1 text-slate-500 font-mono truncate max-w-[160px]">
                    <SettingsIcon size={10} strokeWidth={2} /> {srv.kernel_version}
                  </span>
                )}
              </div>
            </div>
          </label>
        ))}
        {filtered.length === 0 && (
          <div className="py-8 text-center text-slate-500 text-sm">Sunucu bulunamadı</div>
        )}
      </div>
    </div>
  )
}

// ─── Plan history row ─────────────────────────────────────────────────────────
const PlanRow = ({ plan, onView, onDelete, onResume, onCancel, onRerunFailed }: {
  plan: UpdatePlan
  onView: (p: UpdatePlan) => void
  onDelete: (id: number) => void
  onResume: (p: UpdatePlan) => void
  onCancel: (p: UpdatePlan) => void
  onRerunFailed: (p: UpdatePlan) => void
}) => {
  const isRunning  = plan.status === 'running' || plan.status === 'ai_analyzing'
  const canResume  = ['draft', 'ai_done', 'ai_analyzing'].includes(plan.status)
  const canRun     = plan.status === 'ai_done'
  const ut = UPDATE_TYPES.find(t => t.key === plan.update_type)

  return (
    <tr className="border-b border-white/[0.04] hover:bg-cyber-card/40 transition-colors">
      <td className="px-4 py-3">
        <div className="text-sm font-medium text-white">{plan.name}</div>
        <div className="text-xs text-slate-500">{fmtDate(plan.created_at)}</div>
      </td>
      <td className="px-3 py-3 text-xs whitespace-nowrap">{ut?.label}</td>
      <td className="px-3 py-3 whitespace-nowrap">
        <span className={`text-xs font-medium flex items-center gap-1 ${STATUS_COLOR[plan.status]}`}>
          {isRunning && <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse inline-block" />}
          {STATUS_LABEL[plan.status] || plan.status}
        </span>
      </td>
      <td className="px-3 py-3 text-center">
        <div className="text-sm text-white">{plan.completed_servers}/{plan.total_servers}</div>
        {plan.total_servers > 0 && (
          <div className="w-full bg-white/[0.07] rounded-full h-1 mt-1">
            <div className="bg-blue-500 h-1 rounded-full transition-all"
              style={{ width: `${Math.round(plan.completed_servers*100/plan.total_servers)}%` }} />
          </div>
        )}
      </td>
      <td className="px-3 py-3 whitespace-nowrap">
        <div className="flex gap-1 flex-wrap">
          {/* Yeniden Çalıştır — başarısız/kısmi planlar için direkt başlat */}
          {['failed','partial'].includes(plan.status) && (
            <button onClick={() => onRerunFailed(plan)}
              className="px-2.5 py-1 text-xs bg-amber-600/30 hover:bg-amber-600/50 text-amber-300 border border-amber-500/30 rounded-lg transition-colors whitespace-nowrap"
              title="Başarısız işleri yeniden başlat">
              ↻ Tekrar
            </button>
          )}
          {/* Görüntüle — tamamlanmış planlar için */}
          {plan.status === 'completed' && (
            <button onClick={() => onResume(plan)}
              className="px-2.5 py-1 text-xs bg-white/[0.07] hover:bg-slate-600 text-slate-200 rounded-lg transition-colors"
              title="Planı görüntüle">
              ↻
            </button>
          )}
          {/* Devam Et — draft/ai_done/running planlar için */}
          {isRunning && (
            <button onClick={() => onCancel(plan)}
              className="px-2.5 py-1 text-xs bg-red-500/20 text-red-300 border border-red-500/30 hover:bg-red-500/30 rounded-lg transition-colors"
              title="Takılı güncellemeyi iptal et">
              ✕ İptal
            </button>
          )}
          {(canResume || isRunning) && (
            <button onClick={() => onResume(plan)}
              className={`px-2.5 py-1 text-xs rounded-lg transition-colors font-medium ${
                isRunning
                  ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30 hover:bg-blue-500/30'
                  : canRun
                  ? 'bg-green-700 hover:bg-green-600 text-white'
                  : 'bg-white/[0.07] hover:bg-slate-600 text-slate-200'
              }`}>
              {isRunning ? '● İzle' : canRun ? '▶ Çalıştır' : '↩ Devam'}
            </button>
          )}
          <button onClick={() => onView(plan)}
            className="px-2.5 py-1 text-xs bg-white/[0.07] hover:bg-slate-600 text-slate-200 rounded-lg transition-colors">
            Detay
          </button>
          {!isRunning && (
            <button onClick={() => onDelete(plan.id)}
              className="px-2.5 py-1 text-xs text-red-400 hover:bg-red-700/30 rounded-lg transition-colors">
              Sil
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}

// ─── Plan detail modal ────────────────────────────────────────────────────────
const PlanDetailModal = ({ plan, onClose }: { plan: UpdatePlan; onClose: () => void }) => {
  const [jobs,         setJobs]         = useState<UpdateJob[]>([])
  const [sel,          setSel]          = useState<UpdateJob|null>(null)
  const [jobAnalysis,  setJobAnalysis]  = useState<Record<number,string>>({})
  const [analyzingJob, setAnalyzingJob] = useState<number|null>(null)

  const analyzeJobError = async (job: UpdateJob) => {
    setAnalyzingJob(job.id)
    try {
      const r = await fetch(`${API}/plans/${plan.id}/jobs/${job.id}/analyze-error`, { method: 'POST' })
      if (r.ok) {
        const d = await r.json()
        setJobAnalysis(prev => ({ ...prev, [job.id]: d.analysis }))
      }
    } finally { setAnalyzingJob(null) }
  }

  const load = useCallback(async () => {
    const r = await fetch(`${API}/plans/${plan.id}/jobs`)
    if (r.ok) setJobs(await r.json())
  }, [plan.id])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const running = jobs.some(j => j.status === 'running' || j.status === 'pending')
    if (!running) return
    const t = setInterval(load, 4000)
    return () => clearInterval(t)
  }, [jobs, load])

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-cyber-card border border-white/[0.06] rounded-2xl w-full max-w-5xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06] flex-shrink-0">
          <div>
            <h2 className="text-lg font-semibold text-white">{plan.name}</h2>
            <span className={`text-xs font-medium ${STATUS_COLOR[plan.status]}`}>
              {STATUS_LABEL[plan.status]} · {plan.completed_servers}/{plan.total_servers}
            </span>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-2xl">×</button>
        </div>
        <div className="flex-1 overflow-hidden flex">
          {/* Left: server list */}
          <div className="w-64 border-r border-white/[0.06] overflow-y-auto flex-shrink-0">
            {plan.ai_analysis && (
              <div className="p-3 border-b border-white/[0.06] bg-cyan-500/5">
                <div className="text-xs font-semibold text-cyan-400 mb-1">AI Analiz</div>
                <div className="text-xs text-slate-300 line-clamp-5 leading-relaxed">{plan.ai_analysis}</div>
              </div>
            )}
            {plan.ai_summary && (
              <div className="p-3 border-b border-white/[0.06] bg-green-500/5">
                <div className="text-xs font-semibold text-green-400 mb-1">AI Özet</div>
                <AiMarkdown text={plan.ai_summary} />
              </div>
            )}
            {jobs.map(j => (
              <button key={j.id} onClick={() => setSel(j)}
                className={`w-full text-left px-4 py-3 hover:bg-white/[0.03] border-b border-white/[0.03] transition-colors ${sel?.id === j.id ? 'bg-blue-600/10' : ''}`}>
                <div className="flex items-center gap-2">
                  <span className={`text-xs ${STATUS_COLOR[j.status]}`}>
                    {(j.status==='running'||j.status==='pending') && <span className="inline-block w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse mr-1" />}
                    {STATUS_LABEL[j.status]}
                  </span>
                  {j.reboot_required && <span className="text-yellow-400 text-xs font-bold">!</span>}
                </div>
                <div className="text-sm font-medium text-white truncate">{j.server_name}</div>
                <div className="text-xs text-slate-400">{j.server_ip}</div>
                {j.os_type && <div className="text-xs text-blue-400">{j.os_type.toUpperCase()} {j.os_version}</div>}
                {j.packages_updated.length > 0 && <div className="text-xs text-green-400">{j.packages_updated.length} paket güncellendi</div>}
              </button>
            ))}
          </div>
          {/* Right: job detail */}
          <div className="flex-1 overflow-y-auto p-5">
            {sel ? (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div className="bg-white/[0.07]/50 rounded-lg p-3"><div className="text-slate-400">Başlangıç</div><div className="text-white">{fmtDate(sel.started_at)}</div></div>
                  <div className="bg-white/[0.07]/50 rounded-lg p-3"><div className="text-slate-400">Bitiş</div><div className="text-white">{fmtDate(sel.completed_at)}</div></div>
                </div>
                {sel.reboot_required && (
                  <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl px-4 py-3 text-sm text-yellow-300">
                    Sistem yeniden başlatma gerekiyor
                  </div>
                )}
                {sel.packages_to_update.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold text-slate-300 mb-2">Güncellenecek ({sel.packages_to_update.length})</div>
                    <div className="bg-cyber-deep rounded-xl p-3 max-h-40 overflow-y-auto space-y-0.5">
                      {sel.packages_to_update.slice(0,30).map((p,i) => (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          {p.is_security && <Lock size={12} strokeWidth={2} className="text-red-400 flex-shrink-0" />}
                          {p.is_kernel   && <Zap size={12} strokeWidth={2} className="text-blue-400 flex-shrink-0" />}
                          <span className="text-slate-200 font-mono">{p.name}</span>
                          {p.new_version && <span className="text-slate-400">→ {p.new_version}</span>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {sel.status === 'completed' && (
                  <PackageList job={sel} planId={plan.id} />
                )}
                {['completed','failed','partial'].includes(sel.status) && (
                  <button
                    onClick={async () => {
                      if (!confirm(`"${sel.server_name}" için yeniden çalıştırılsın mı?`)) return
                      const r = await fetch(`${API}/plans/${plan.id}/jobs/${sel.id}/rerun`, { method: 'POST' })
                      if (r.ok) { load(); alert('↻ Yeniden başlatıldı') }
                      else alert((await r.json()).detail || 'Hata')
                    }}
                    className="flex items-center gap-1.5 px-3 py-2 text-xs bg-white/[0.07] hover:bg-slate-600 text-slate-200 border border-slate-600 rounded-lg transition-colors w-full justify-center font-medium"
                  >
                    ↻ Yeniden Çalıştır
                  </button>
                )}
                {sel.log && (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-xs font-semibold text-slate-300">Çıktı</div>
                      {sel.status === 'failed' && (
                        <button
                          onClick={() => analyzeJobError(sel)}
                          disabled={analyzingJob === sel.id}
                          className="flex items-center gap-1.5 px-2.5 py-1 text-xs bg-cyan-700/40 hover:bg-cyan-700/60 text-cyan-300 border border-cyan-600/30 rounded-lg transition-colors disabled:opacity-40"
                        >
                          {analyzingJob === sel.id
                            ? <><div className="w-3 h-3 border border-white/40 border-t-white rounded-full animate-spin" />Analiz ediliyor...</>
                            : 'Hatayı Analiz Et'}
                        </button>
                      )}
                    </div>
                    {/* AI hata analizi */}
                        {jobAnalysis[sel.id] && (
                      <div className="mb-3 space-y-2">
                        <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-xl p-3">
                          <div className="text-xs font-semibold text-cyan-400 mb-2">AI Analiz</div>
                          <AiMarkdown text={jobAnalysis[sel.id]} />
                        </div>
                        <button
                          onClick={async () => {
                            if (!confirm('AI önerilen parametrelerle güncelleme yeniden çalıştırılacak. Devam?')) return
                            const r = await fetch(`${API}/plans/${plan.id}/jobs/${sel.id}/retry-with-fix`, { method: 'POST' })
                            if (r.ok) {
                              const d = await r.json()
                              load()
                              alert(`✓ Yeniden başlatıldı: ${d.fix}`)
                            } else {
                              alert('Hata: ' + (await r.json()).detail)
                            }
                          }}
                          className="flex items-center gap-2 px-3 py-2 text-xs bg-green-700/30 hover:bg-green-700/50 text-green-300 border border-green-600/30 rounded-lg transition-colors w-full justify-center font-medium"
                        >
                          AI Önerilen Çözümü Uygula & Yeniden Başlat
                        </button>
                      </div>
                    )}
                    <pre className="bg-cyber-deep border border-white/[0.06] rounded-xl p-4 text-xs text-green-300 font-mono whitespace-pre-wrap max-h-52 overflow-y-auto">{sel.log}</pre>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex items-center justify-center h-full text-slate-500 text-sm">← Detay için sunucu seçin</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Package List ─────────────────────────────────────────────────────────────
const PackageList: React.FC<{ job: UpdateJob; planId: number }> = ({ job, planId }) => {
  const [packages, setPackages] = React.useState<any[]>(job.packages_updated || [])
  const [loading,  setLoading]  = React.useState(false)
  const [fetched,  setFetched]  = React.useState(false)

  const fetchPackages = async () => {
    setLoading(true)
    try {
      const r = await fetch(`${API}/plans/${planId}/jobs/${job.id}/fetch-packages`, { method: 'POST' })
      if (r.ok) {
        const d = await r.json()
        setPackages(d.packages || [])
        setFetched(true)
      }
    } finally { setLoading(false) }
  }

  if (packages.length === 0 && !fetched) {
    return (
      <div className="flex items-center justify-between bg-cyber-card/50 rounded-lg px-3 py-2">
        <span className="text-xs text-slate-500">Güncellenen paket listesi yüklenmedi</span>
        <button onClick={fetchPackages} disabled={loading}
          className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 px-2 py-1 hover:bg-white/[0.06] rounded transition-colors disabled:opacity-40">
          {loading ? <><div className="w-3 h-3 border border-blue-400 border-t-transparent rounded-full animate-spin" />Getiriliyor...</> : 'SSH ile Listele'}
        </button>
      </div>
    )
  }

  if (packages.length === 0 && fetched) {
    return <div className="text-xs text-slate-500 italic px-1">Bu işlemde güncellenen paket bulunamadı (zaten günceldi)</div>
  }

  return (
    <div>
      <div className="text-xs font-semibold text-green-300 mb-1.5">✓ Güncellenen Paketler ({packages.length})</div>
      <div className="flex flex-wrap gap-1 max-h-40 overflow-y-auto">
        {packages.map((p: any, i: number) => (
          <span key={i} className="text-[11px] bg-green-500/10 text-green-300 border border-green-500/20 px-1.5 py-0.5 rounded font-mono">
            {p.name}{p.version ? <span className="text-green-600 ml-1">{p.version.split('-')[0]}</span> : null}
          </span>
        ))}
      </div>
    </div>
  )
}

// ─── Live Job Log ─────────────────────────────────────────────────────────────
const LiveJobLog: React.FC<{
  job: UpdateJob
  planId: number
  onAnalyze: () => void
  analyzing: boolean
  aiResult: string | null
}> = ({ job, planId, onAnalyze, analyzing, aiResult }) => {
  const [liveLog, setLiveLog] = React.useState(job.log || '')
  const logRef = React.useRef<HTMLPreElement>(null)
  const isActive = job.status === 'running' || job.status === 'pending'

  // Aktif job'da 1.5s'de bir log'u çek
  useEffect(() => {
    if (!isActive) { setLiveLog(job.log || ''); return }
    const poll = async () => {
      const r = await fetch(`${API}/plans/${planId}/jobs`)
      if (r.ok) {
        const jobs: UpdateJob[] = await r.json()
        const updated = jobs.find(j => j.id === job.id)
        if (updated?.log) setLiveLog(updated.log)
      }
    }
    poll()
    const t = setInterval(poll, 1500)
    return () => clearInterval(t)
  }, [job.id, planId, isActive])

  // Log değişince en alta scroll
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [liveLog])

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
          İşlem Logu
          {isActive && <span className="flex items-center gap-1 text-green-400 font-normal"><span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />Canlı</span>}
        </div>
        {job.status === 'failed' && (
          <button onClick={onAnalyze} disabled={analyzing}
            className="flex items-center gap-1 px-2 py-0.5 text-xs bg-cyan-700/30 hover:bg-cyan-700/50 text-cyan-300 border border-cyan-600/30 rounded transition-colors disabled:opacity-40">
            {analyzing ? <><div className="w-3 h-3 border border-white/40 border-t-white rounded-full animate-spin" />...</> : 'Hatayı Analiz Et'}
          </button>
        )}
      </div>
                      {aiResult && (
                        <div className="mb-2 space-y-2">
                          <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-lg p-4"><AiMarkdown text={aiResult} /></div>
                          {/* Çözümü Uygula butonu */}
                          <button
                            onClick={async () => {
                              if (!confirm('AI önerilen parametrelerle güncelleme yeniden çalıştırılacak. Devam?')) return
                              const r = await fetch(`${API}/plans/${planId}/jobs/${job.id}/retry-with-fix`, { method: 'POST' })
                              if (r.ok) {
                                const d = await r.json()
                                alert(`✓ Yeniden başlatıldı: ${d.fix}`)
                              } else {
                                alert('Hata: ' + (await r.json()).detail)
                              }
                            }}
                            className="flex items-center gap-2 px-3 py-2 text-xs bg-green-700/30 hover:bg-green-700/50 text-green-300 border border-green-600/30 rounded-lg transition-colors w-full justify-center font-medium"
                          >
                            AI Önerilen Çözümü Uygula & Güncellemeyi Yeniden Başlat
                          </button>
                        </div>
                      )}
      {liveLog ? (
        <pre ref={logRef}
          className="bg-cyber-deep border border-white/[0.06]/50 rounded-lg p-3 text-[11px] text-green-300 font-mono whitespace-pre-wrap max-h-64 overflow-y-auto leading-relaxed">
          {liveLog}
        </pre>
      ) : isActive ? (
        <div className="bg-cyber-deep border border-white/[0.06]/50 rounded-lg p-4 flex items-center gap-3">
          <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin flex-shrink-0" />
          <div className="text-xs text-slate-400">Güncelleme başlatılıyor, log bekleniyor...</div>
        </div>
      ) : null}
    </div>
  )
}

// ─── AI Markdown Renderer ─────────────────────────────────────────────────────
const AiMarkdown: React.FC<{ text: string }> = ({ text }) => {
  // Bold inline: **text** → <strong>
  const renderInline = (t: string) => {
    const parts = t.split(/\*\*(.+?)\*\*/g)
    return parts.map((p, i) =>
      i % 2 === 1
        ? <strong key={i} className="text-white font-semibold">{p}</strong>
        : <span key={i}>{p}</span>
    )
  }

  const lines = text.split('\n')
  const nodes: React.ReactNode[] = []
  let i = 0

  while (i < lines.length) {
    const raw   = lines[i]
    const line  = raw.trim()
    i++

    if (!line) { nodes.push(<div key={i} className="h-1.5" />); continue }

    // H1: # Başlık veya tamamen **bold**
    if (line.startsWith('# ') || (line.startsWith('**') && line.endsWith('**') && !line.slice(2,-2).includes('**'))) {
      const title = line.replace(/^#+\s*/, '').replace(/\*\*/g, '')
      nodes.push(
        <h3 key={i} className="text-sm font-bold text-white mt-4 mb-1.5 flex items-center gap-2">
          <span className="w-1 h-4 bg-cyan-500 rounded-full flex-shrink-0" />
          {title}
        </h3>
      )
      continue
    }

    // H2: ## veya Numbered bold "1. **Başlık**"
    if (line.startsWith('## ') || line.match(/^\d+\.\s+\*\*/)) {
      const title = line.replace(/^##\s*/, '').replace(/^\d+\.\s+/, '').replace(/\*\*/g, '')
      nodes.push(
        <div key={i} className="flex items-center gap-2 mt-3 mb-1">
          <span className="text-cyan-400 font-bold text-xs flex-shrink-0">
            {line.match(/^(\d+)\./) ? line.match(/^(\d+)\./)?.[1] + '.' : '▸'}
          </span>
          <span className="text-sm font-semibold text-cyan-200">{title}</span>
        </div>
      )
      continue
    }

    // Alert satırları — backend güncelleme script'leri log satırlarının başına
    // emoji koyuyor; bunu eşleştirip ayrıştırıyoruz ama kullanıcıya ham emoji
    // yerine lucide-react ikonu gösteriyoruz (DESIGN.md: "emoji UI elementi olamaz").
    const alertMatch = line.match(/^(⚠️|✅|❌|🔴|🟡|🟢|🔒|⚡|🔄|💡|📋|🛡️)/)
    if (alertMatch) {
      const icon = alertMatch[1]
      const alertMeta: Record<string, { cls: string; Icon: typeof AlertTriangle }> = {
        '⚠️': { cls: 'bg-yellow-500/10 border-yellow-500/30 text-yellow-200', Icon: AlertTriangle },
        '✅': { cls: 'bg-green-500/10 border-green-500/30 text-green-200', Icon: CheckCircle2 },
        '❌': { cls: 'bg-red-500/10 border-red-500/30 text-red-200', Icon: XCircle },
        '🔴': { cls: 'bg-red-500/10 border-red-500/30 text-red-200', Icon: XCircle },
        '🟡': { cls: 'bg-yellow-500/10 border-yellow-500/30 text-yellow-200', Icon: AlertTriangle },
        '🟢': { cls: 'bg-green-500/10 border-green-500/30 text-green-200', Icon: CheckCircle2 },
        '🔒': { cls: 'bg-orange-500/10 border-orange-500/30 text-orange-200', Icon: Lock },
        '⚡': { cls: 'bg-blue-500/10 border-blue-500/30 text-blue-200', Icon: Zap },
        '🔄': { cls: 'bg-blue-500/10 border-blue-500/30 text-blue-200', Icon: RefreshCw },
        '💡': { cls: 'bg-blue-500/10 border-blue-500/30 text-blue-200', Icon: Lightbulb },
        '📋': { cls: 'bg-slate-500/10 border-slate-500/30 text-slate-200', Icon: ClipboardList },
        '🛡️': { cls: 'bg-orange-500/10 border-orange-500/30 text-orange-200', Icon: Shield },
      }
      const meta = alertMeta[icon] || { cls: 'bg-cyber-card/50 border-slate-600 text-slate-200', Icon: AlertTriangle }
      const AlertIcon = meta.Icon
      nodes.push(
        <div key={i} className={`flex gap-2.5 border rounded-lg px-3 py-2 my-1 text-xs leading-relaxed ${meta.cls}`}>
          <AlertIcon size={14} strokeWidth={2} className="flex-shrink-0 mt-0.5" />
          <span>{renderInline(line.replace(alertMatch[0], '').trim())}</span>
        </div>
      )
      continue
    }

    // Liste: - veya • veya *
    if (line.match(/^[-•*]\s+/)) {
      const content = line.replace(/^[-•*]\s+/, '')
      nodes.push(
        <div key={i} className="flex gap-2 py-0.5 pl-1">
          <span className="text-cyan-500 flex-shrink-0 mt-0.5">›</span>
          <span className="text-sm text-slate-300 leading-relaxed">{renderInline(content)}</span>
        </div>
      )
      continue
    }

    // Numbered list: 1. item
    const numMatch = line.match(/^(\d+)\.\s+(.+)/)
    if (numMatch) {
      nodes.push(
        <div key={i} className="flex gap-2.5 py-0.5 pl-1">
          <span className="text-cyan-500/70 font-mono text-xs flex-shrink-0 mt-0.5 w-4">{numMatch[1]}.</span>
          <span className="text-sm text-slate-300 leading-relaxed">{renderInline(numMatch[2])}</span>
        </div>
      )
      continue
    }

    // Code/command: `kod`
    if (line.includes('`')) {
      const parts = line.split(/`(.+?)`/g)
      nodes.push(
        <p key={i} className="text-sm text-slate-300 leading-relaxed py-0.5">
          {parts.map((p, j) =>
            j % 2 === 1
              ? <code key={j} className="bg-cyber-card border border-slate-600 text-green-300 px-1.5 py-0.5 rounded text-[11px] font-mono mx-0.5">{p}</code>
              : <span key={j}>{renderInline(p)}</span>
          )}
        </p>
      )
      continue
    }

    // Normal paragraf
    nodes.push(
      <p key={i} className="text-sm text-slate-300 leading-relaxed py-0.5">
        {renderInline(line)}
      </p>
    )
  }

  return <div className="space-y-0.5">{nodes}</div>
}

// ─── Reboot Panel ────────────────────────────────────────────────────────────
const RebootPanel: React.FC<{ loadPlans: () => void }> = ({ loadPlans: _loadPlans }) => {
  const [rebootJobs, setRebootJobs] = useState<any[]>([])
  const [rebooting,  setRebooting]  = useState(false)
  const [selected,   setSelected]   = useState<Set<number>>(new Set())

  useEffect(() => {
    // Tamamlanmış ama reboot gereken job'ları çek
    const fetchRebootJobs = async () => {
      const r = await fetch(`${API}/plans?limit=50`)
      if (!r.ok) return
      const plans = await r.json()
      const jobs: any[] = []
      for (const plan of plans) {
        const jr = await fetch(`${API}/plans/${plan.id}/jobs`)
        if (!jr.ok) continue
        const planJobs: UpdateJob[] = await jr.json()
        for (const j of planJobs) {
          if (j.reboot_required && j.status === 'completed') {
            jobs.push({ ...j, plan_name: plan.name })
          }
        }
      }
      setRebootJobs(jobs)
    }
    fetchRebootJobs()
  }, [])

  const handleReboot = async () => {
    if (selected.size === 0) { alert('Sunucu seçin'); return }
    if (!confirm(`${selected.size} sunucu 1 dakika sonra yeniden başlatılacak. Emin misiniz?`)) return
    setRebooting(true)
    const serverIds = rebootJobs.filter(j => selected.has(j.id)).map(j => j.server_id)
    const r = await fetch(`${API}/reboot-servers`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(serverIds),
    })
    setRebooting(false)
    if (r.ok) {
      const d = await r.json()
      const ok = Object.values(d.results).filter((v: any) => v.success).length
      alert(`✓ ${ok} sunucu için reboot planlandı (1 dakika sonra)`)
      // Listeden kaldır
      setRebootJobs(prev => prev.filter(j => !selected.has(j.id)))
      setSelected(new Set())
    }
  }

  const handleCancel = async () => {
    if (selected.size === 0) return
    const serverIds = rebootJobs.filter(j => selected.has(j.id)).map(j => j.server_id)
    const r = await fetch(`${API}/cancel-reboot`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(serverIds),
    })
    if (r.ok) alert('Reboot iptal edildi')
  }

  if (rebootJobs.length === 0) return null

  return (
    <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-yellow-500/20">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 bg-yellow-400 rounded-full animate-pulse" />
          <span className="text-sm font-semibold text-yellow-300">
            Reboot Bekleyen Sunucular ({rebootJobs.length})
          </span>
          <span className="text-xs text-yellow-500">Kernel güncellemesi tamamlandı — yeniden başlatma gerekiyor</span>
        </div>
        <div className="flex gap-2">
          <button onClick={handleCancel} disabled={selected.size === 0}
            className="px-3 py-1.5 text-xs border border-slate-600 text-slate-400 hover:text-white rounded-lg transition-colors disabled:opacity-40">
            Reboot'u İptal Et
          </button>
          <button onClick={handleReboot} disabled={rebooting || selected.size === 0}
            className="px-3 py-1.5 text-xs bg-yellow-600 hover:bg-yellow-500 text-white font-semibold rounded-lg transition-colors disabled:opacity-40 flex items-center gap-1.5">
            {rebooting ? <><div className="w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />Yeniden Başlatılıyor...</> : `${selected.size > 0 ? selected.size + ' ' : ''}Seçiliyi Yeniden Başlat`}
          </button>
        </div>
      </div>
      <div className="divide-y divide-yellow-500/10">
        {rebootJobs.map(j => (
          <label key={j.id} className={`flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-yellow-500/5 ${selected.has(j.id) ? 'bg-yellow-500/10' : ''}`}>
            <input type="checkbox" checked={selected.has(j.id)}
              onChange={() => setSelected(prev => { const next = new Set(prev); next.has(j.id) ? next.delete(j.id) : next.add(j.id); return next })}
              className="accent-yellow-500 w-4 h-4 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-white">{j.server_name}</div>
              <div className="text-xs text-slate-400">{j.server_ip} · {j.plan_name}</div>
            </div>
            <div className="text-xs text-slate-500 flex-shrink-0">{fmtDate(j.completed_at)}</div>
          </label>
        ))}
      </div>
      <div className="flex items-start gap-1.5 px-4 py-2.5 bg-yellow-500/5 text-xs text-yellow-600">
        <Lightbulb size={12} strokeWidth={2} className="flex-shrink-0 mt-0.5" />
        <span>"Seçiliyi Yeniden Başlat" tıklayınca 1 dakika geri sayım başlar. İptal için "Reboot'u İptal Et" kullanın.</span>
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────
const SystemUpdate: React.FC = () => {
  const [step, setStep]       = useState(1)
  const [maxStep, setMaxStep] = useState(1)  // ulaşılan en yüksek adım
  const [showWizard, setShowWizard] = useState(false)

  // Wizard state
  const [selectedDistro,  setSelectedDistro]  = useState('')        // adım 1
  const [servers,         setServers]          = useState<ServerItem[]>([])
  const [selectedServers, setSelectedServers]  = useState<number[]>([])
  // Adım 3 — Yetkili kullanıcı
  const [credMode,      setCredMode]     = useState<'stored'|'override'>('stored')
  // Adım 5 — Update check sonuçları
  const [checkResult,    setCheckResult]   = useState<Record<string, any>>({})
  const [checking,       setChecking]      = useState(false)
  // Custom mod — seçili paketler
  const [selectedPkgs,   setSelectedPkgs]  = useState<Set<string>>(new Set())
  const [pkgSearch,      setPkgSearch]     = useState('')
  const [overrideUser, setOverrideUser] = useState('')
  const [overridePass, setOverridePass] = useState('')
  const [overrideSudo, setOverrideSudo] = useState('')
  const [privMethod,   setPrivMethod]   = useState<'sudo'|'dzdo'|'direct'>('sudo')
  // Adım 4 — Repo
  const [repos,           setRepos]            = useState<RepoSource[]>([])
  const [filteredRepos,   setFilteredRepos]    = useState<RepoSource[]>([])
  const [selectedRepo,    setSelectedRepo]     = useState<number|null>(null)
  // Adım 5 — VM Snapshot
  const [snapshotMode,      setSnapshotMode]      = useState<'take'|'skip'>('take')
  const [snapshotRetention, setSnapshotRetention] = useState<'1d'|'1w'|'1m'|'indefinite'>('1w')
  const [snapCapability,    setSnapCapability]    = useState<{total:number; snapshot_ready:number; snapshot_missing:number; servers:{server_id:number; can_snapshot:boolean; server_name?:string; reason?:string}[]} | null>(null)
  // Adım 6 — Mod
  const [updateType,      setUpdateType]       = useState('')
  const [planName,        setPlanName]         = useState('')
  const [analyzing,       setAnalyzing]        = useState(false)
  const [aiAnalysis,      setAiAnalysis]       = useState('')
  const [currentPlan,     setCurrentPlan]      = useState<UpdatePlan|null>(null)
  const [planJobs,        setPlanJobs]         = useState<UpdateJob[]>([])
  const [expandedJob,     setExpandedJob]      = useState<number|null>(null)

  // İş aktif mi? (adım kilidi için)
  const isJobActive = (
    currentPlan?.status === 'running' ||
    currentPlan?.status === 'ai_analyzing' ||
    planJobs.some(j => j.status === 'running' || j.status === 'pending')
  )
  const [liveJobAi,       setLiveJobAi]        = useState<Record<number,string>>({})
  const [liveAiLoading,   setLiveAiLoading]    = useState<number|null>(null)

  // History
  const [plans,    setPlans]    = useState<UpdatePlan[]>([])
  const [viewPlan, setViewPlan] = useState<UpdatePlan|null>(null)
  const [toast,    setToast]    = useState<{msg:string; type:'ok'|'err'}|null>(null)

  const toastTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const showToast = (msg: string, type: 'ok'|'err' = 'ok') => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
    setToast({msg, type})
    toastTimerRef.current = setTimeout(() => setToast(null), 5000)
  }
  React.useEffect(() => () => { if (toastTimerRef.current) clearTimeout(toastTimerRef.current) }, [])

  const loadPlans = useCallback(async () => {
    const r = await fetch(`${API}/plans`)
    if (r.ok) setPlans(await r.json())
  }, [])

  // Load all repos once
  // maxStep — ulaşılan en yüksek adımı takip et
  useEffect(() => {
    setMaxStep(prev => Math.max(prev, step))
  }, [step])

  useEffect(() => {
    loadPlans()
    fetch('/api/v1/repos', { headers: authHeaders() }).then(r => r.json()).then(setRepos).catch((e: Error) => console.warn('Repo listesi yüklenemedi:', e.message))
  }, [loadPlans])

  // Auto-refresh plans
  useEffect(() => {
    const running = plans.some(p => p.status === 'running' || p.status === 'ai_analyzing')
    if (!running) return
    const t = setInterval(loadPlans, 5000)
    return () => clearInterval(t)
  }, [plans, loadPlans])

  // When distro changes → load servers + filter repos
  useEffect(() => {
    if (!showWizard) return
    const distroObj = DISTRO_LIST.find(d => d.key === selectedDistro)

    // Sunucuları yükle
    const url = selectedDistro
      ? `/api/v1/updates/servers?distro=${distroObj?.match[0] || selectedDistro}`
      : '/api/v1/updates/servers'
    fetch(url, { headers: authHeaders() }).then(r => r.json()).then(setServers).catch((e: Error) => console.warn('Sunucular yüklenemedi:', e.message))

    // Repoları filtrele
    if (selectedDistro === '') {
      setFilteredRepos(repos.filter(r => ['synced','partial'].includes(r.sync_status)))
    } else {
      const typeMap: Record<string, string[]> = {
        rhel: ['rhel'], oel: ['oel'], rocky: ['rocky'], ubuntu: ['ubuntu'],
      }
      const types = typeMap[selectedDistro] || [selectedDistro]
      setFilteredRepos(repos.filter(r => types.includes(r.repo_type) && ['synced','partial'].includes(r.sync_status)))
    }
  }, [selectedDistro, repos, showWizard])

  // Snapshot uygunluğu — adım 5
  useEffect(() => {
    if (step !== 5 || selectedServers.length === 0) return
    fetch(`/api/v1/snapshots/capability?server_ids=${selectedServers.join(',')}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => setSnapCapability(d))
      .catch(() => setSnapCapability(null))
  }, [step, selectedServers])

  // Auto-refresh current plan jobs
  useEffect(() => {
    if (!currentPlan || currentPlan.status !== 'running') return
    const refresh = async () => {
      const [pr, jr] = await Promise.all([
        fetch(`${API}/plans/${currentPlan.id}`),
        fetch(`${API}/plans/${currentPlan.id}/jobs`),
      ])
      if (pr.ok) setCurrentPlan(await pr.json())
      if (jr.ok) {
        const jobs: UpdateJob[] = await jr.json()
        setPlanJobs(jobs)
        // Çalışan job'u otomatik aç
        const runningJob = jobs.find(j => j.status === 'running' || j.status === 'pending')
        if (runningJob) setExpandedJob(prev => prev ?? runningJob.id)
      }
    }
    refresh()
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [currentPlan?.id, currentPlan?.status])

  // ── Handlers ────────────────────────────────────────────────────────────────
  const handleCreatePlan = async () => {
    const name = planName ||
      `${DISTRO_LIST.find(d=>d.key===selectedDistro)?.short || 'Tüm'} — ${UPDATE_TYPES.find(t=>t.key===updateType)?.label} — ${new Date().toLocaleDateString('tr-TR')}`
    const body: any = {
      name, update_type: updateType, server_ids: selectedServers,
      repo_id: selectedRepo || undefined,
      distro_filter: selectedDistro || undefined,
    }
    if (credMode === 'override' && overrideUser) {
      body.override_username      = overrideUser
      body.override_password      = overridePass || undefined
      body.override_sudo_password = overrideSudo || overridePass || undefined
    }
    body.priv_method = privMethod
    if (updateType === 'custom') {
      body.custom_packages = Array.from(selectedPkgs)
    }
    body.snapshot_mode = snapshotMode
    body.snapshot_retention = snapshotRetention
    const r = await fetch(`${API}/plans`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (r.ok) { setCurrentPlan(await r.json()); setStep(7) }
  }

  const handleAnalyze = async () => {
    if (!currentPlan) return
    setAnalyzing(true)
    try {
      const r = await fetch(`${API}/plans/${currentPlan.id}/analyze`, { method: 'POST' })
      if (r.ok) {
        const d = await r.json()
        setAiAnalysis(d.analysis)
        const pr = await fetch(`${API}/plans/${currentPlan.id}`)
        if (pr.ok) setCurrentPlan(await pr.json())
        setStep(8)
      }
    } finally { setAnalyzing(false) }
  }

  const handleRun = async () => {
    if (!currentPlan) return
    const r = await fetch(`${API}/plans/${currentPlan.id}/run`, { method: 'POST' })
    if (r.ok) {
      const [pr, jr] = await Promise.all([
        fetch(`${API}/plans/${currentPlan.id}`),
        fetch(`${API}/plans/${currentPlan.id}/jobs`),
      ])
      if (pr.ok) setCurrentPlan(await pr.json())
      if (jr.ok) setPlanJobs(await jr.json())
      setStep(9)
      showToast('Güncelleme başlatıldı')
      await loadPlans()
    }
  }

  const handleResumePlan = async (plan: UpdatePlan) => {
    // Plan state'ini geri yükle
    const resumeMax = plan.status === 'running' ? 9 : plan.status === 'ai_done' ? 8 : plan.ai_analysis ? 7 : 6
    setMaxStep(resumeMax)
    setCurrentPlan(plan)
    setUpdateType(plan.update_type)
    setSelectedServers(plan.server_ids || [])
    if (plan.ai_analysis) setAiAnalysis(plan.ai_analysis)

    // Distro filtresi ve override credential
    if ((plan as any).distro_filter) setSelectedDistro((plan as any).distro_filter || '')
    if ((plan as any).has_override_creds && (plan as any).override_username) {
      setCredMode('override')
      setOverrideUser((plan as any).override_username || '')
    }
    if ((plan as any).priv_method) setPrivMethod((plan as any).priv_method || 'sudo')
    if ((plan as any).repo_id) setSelectedRepo((plan as any).repo_id)
    if ((plan as any).snapshot_mode) setSnapshotMode((plan as any).snapshot_mode === 'skip' ? 'skip' : 'take')
    if ((plan as any).snapshot_retention) setSnapshotRetention((plan as any).snapshot_retention || '1w')

    // Jobs'ları yükle
    const jr = await fetch(`${API}/plans/${plan.id}/jobs`)
    if (jr.ok) setPlanJobs(await jr.json())

    // Sunucu listesini distro'ya göre yükle
    const distro = (plan as any).distro_filter || ''
    const url = distro ? `/api/v1/updates/servers?distro=${distro}` : '/api/v1/updates/servers'
    fetch(url).then(r => r.json()).then(setServers).catch(() => {})

    // Duruma göre doğru adıma git
    if (plan.status === 'running' || plan.status === 'ai_analyzing') {
      setStep(9)   // canlı izleme
    } else if (plan.status === 'ai_done') {
      setStep(8)   // onayla adımı
    } else if (['completed','failed','partial'].includes(plan.status)) {
      setStep(8)
    } else {
      setStep(plan.ai_analysis ? 7 : 6)   // AI analiz veya güncelleme modu
    }
    setShowWizard(true)
  }

  const handleDeletePlan = async (id: number) => {
    if (!confirm('Plan silinsin mi?')) return
    const r = await fetch(`${API}/plans/${id}`, { method: 'DELETE' })
    if (r.ok) { showToast('Silindi'); await loadPlans() }
    else showToast('Hata', 'err')
  }

  const handleRerunFailed = async (plan: UpdatePlan) => {
    const r = await fetch(`${API}/plans/${plan.id}/rerun-failed`, { method: 'POST' })
    const data = await r.json().catch(() => ({}))
    if (r.ok) {
      showToast(`↻ ${data.message || 'Yeniden başlatıldı'}`)
      await loadPlans()
      // Canlı izleme için planı aç
      setCurrentPlan(plan)
      const jr = await fetch(`${API}/plans/${plan.id}/jobs`)
      if (jr.ok) setPlanJobs(await jr.json())
      setStep(9)
      setShowWizard(true)
    } else {
      showToast(data.detail || 'Yeniden başlatılamadı', 'err')
    }
  }

  const handleCancelPlan = async (plan: UpdatePlan) => {
    if (!confirm(`"${plan.name}" güncellemesi iptal edilsin mi?`)) return
    const r = await fetch(`${API}/plans/${plan.id}/cancel`, { method: 'POST' })
    if (r.ok) {
      showToast('Güncelleme iptal edildi')
      if (currentPlan?.id === plan.id) {
        const pr = await fetch(`${API}/plans/${plan.id}`)
        if (pr.ok) setCurrentPlan(await pr.json())
      }
      await loadPlans()
    } else {
      const err = await r.json().catch(() => ({}))
      showToast(err.detail || 'İptal edilemedi', 'err')
    }
  }

  const resetWizard = () => {
    setStep(1); setSelectedDistro(''); setSelectedServers([]); setSelectedRepo(null)
    setUpdateType(''); setPlanName(''); setAiAnalysis('')
    setCredMode('stored'); setOverrideUser(''); setOverridePass(''); setOverrideSudo(''); setPrivMethod('sudo')
    setCheckResult({}); setChecking(false); setSelectedPkgs(new Set()); setPkgSearch('')
    setSnapshotMode('take'); setSnapshotRetention('1w'); setSnapCapability(null)
    setMaxStep(1); setExpandedJob(null); setLiveJobAi({}); setLiveAiLoading(null)
    setCurrentPlan(null); setPlanJobs([]); setShowWizard(false)
    loadPlans()
  }

  const distroServerCount = servers.length
  const onlineCount = servers.filter(s => s.status === 'ONLINE').length

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Sistem Güncelleme</h1>
          <p className="text-slate-400 text-sm mt-1">AI destekli — distro bazlı güvenlik, kernel ve tam sistem güncellemeleri</p>
        </div>
        {!showWizard && (
          <div className="flex items-center gap-3">
            {/* Çalışan plan varsa "İzle" butonu göster */}
            {plans.filter(p => p.status === 'running' || p.status === 'ai_analyzing').map(p => (
              <button key={p.id} onClick={() => {
                setCurrentPlan(p)
                setStep(9)   // canlı izleme adımına git
                setShowWizard(true)
                // Jobs'ları da yükle
                fetch(`${API}/plans/${p.id}/jobs`).then(r => r.ok ? r.json() : []).then(setPlanJobs)
              }}
                className="flex items-center gap-2 px-4 py-2.5 bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/40 text-blue-300 font-semibold text-sm rounded-xl transition-colors animate-pulse"
              >
                <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse" />
                {p.name.length > 25 ? p.name.slice(0, 25) + '…' : p.name} — İzle
              </button>
            ))}
            <button onClick={() => setShowWizard(true)}
              className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl transition-colors">
              + Yeni Güncelleme
            </button>
          </div>
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-xl border shadow-lg text-sm font-medium ${
          toast.type==='ok' ? 'bg-green-900/90 border-green-500/50 text-green-300' : 'bg-red-900/90 border-red-500/50 text-red-300'
        }`}>
          <span className="flex items-center gap-1.5">
            {toast.type==='ok' ? <CheckCircle2 size={14} strokeWidth={2} /> : <XCircle size={14} strokeWidth={2} />}
            {toast.msg}
          </span>
        </div>
      )}

      {/* ── WIZARD ────────────────────────────────────────────────────────── */}
      {showWizard && (
        <div className="bg-cyber-card border border-white/[0.06] rounded-2xl p-6">
          {/* Wizard başlığı — her adımda kapat butonu */}
          <div className="flex items-center justify-between mb-4">
            <Steps
              current={step}
              maxReached={maxStep}
              onGoTo={(s) => setStep(s)}
              locked={isJobActive}
            />
            <button
              onClick={() => {
                if (currentPlan && (currentPlan.status === 'running' || currentPlan.status === 'ai_analyzing')) {
                  if (!confirm('Güncelleme devam ediyor. Arka planda çalışmaya devam edecek. Çıkmak istiyor musunuz?')) return
                }
                setShowWizard(false)
              }}
              className="ml-4 flex-shrink-0 text-slate-400 hover:text-white hover:bg-white/[0.06] px-3 py-1.5 rounded-lg text-sm transition-colors flex items-center gap-1.5"
              title="Wizard'ı kapat"
            >
              <span className="text-lg leading-none">×</span>
              <span className="text-xs">Kapat</span>
            </button>
          </div>

          {/* ── Adım 1: Distro Seç ────────────────────────────────────────── */}
          {step === 1 && (
            <div className="space-y-5">
              <div>
                <h2 className="text-base font-semibold text-white">Dağıtımı Seçin</h2>
                <p className="text-xs text-slate-400 mt-0.5">Hangi Linux dağıtımını güncelleyeceksiniz?</p>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                {DISTRO_LIST.map(d => {
                  const isSelected = selectedDistro === d.key
                  return (
                    <button key={d.key} onClick={() => setSelectedDistro(d.key)}
                      className={`p-5 rounded-xl border-2 text-left transition-all ${
                        isSelected ? d.color + ' border-2' : 'border-slate-600 bg-white/[0.02] hover:border-slate-500 hover:bg-white/[0.04]'
                      }`}>
                      <div className="text-xs font-bold text-slate-400 mb-1">{d.icon}</div>
                      <div className="text-base font-bold text-white">{d.short}</div>
                      <div className="text-xs text-slate-400 mt-0.5">{d.label}</div>
                    </button>
                  )
                })}
              </div>

              <div className="flex justify-between items-center">
                <button onClick={resetWizard} className="text-sm text-slate-400 hover:text-white transition-colors">✕ İptal</button>
                <button onClick={() => setStep(2)} disabled={selectedDistro === undefined || selectedDistro === null}
                  className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl transition-colors">
                  Sunucuları Göster →
                </button>
              </div>
            </div>
          )}

          {/* ── Adım 2: Sunucu Seç ────────────────────────────────────────── */}
          {step === 2 && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <span className="text-xs font-bold text-slate-400">{DISTRO_LIST.find(d=>d.key===selectedDistro)?.icon}</span>
                <div>
                  <h2 className="text-base font-semibold text-white">
                    {DISTRO_LIST.find(d=>d.key===selectedDistro)?.label} Sunucuları
                  </h2>
                  <p className="text-xs text-slate-400">
                    {distroServerCount} sunucu bulundu · {onlineCount} aktif
                    {!selectedDistro && ' (tüm dağıtımlar)'}
                  </p>
                </div>
              </div>

              {/* OS bilgisi yok uyarısı */}
              {servers.some(s => !s.has_os_info) && (
                <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl px-4 py-3 text-xs text-yellow-300 flex items-start justify-between gap-3">
                  <div>
                    <span className="font-medium">{servers.filter(s => !s.has_os_info).length} sunucuda OS bilgisi yok</span>
                    <div className="text-slate-400 mt-0.5">
                      Bu sunucular da listelendi. Doğru distro'ya ait olduklarını doğrulamak için
                      <strong className="text-yellow-300 mx-1">Sunucular → OS Bilgisini Yenile</strong>
                      yapın.
                    </div>
                  </div>
                </div>
              )}

              <ServerSelector servers={servers} selected={selectedServers} onChange={setSelectedServers} />

              {selectedServers.length > 0 && (
                <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl px-4 py-2.5 text-sm text-blue-300">
                  {selectedServers.length} sunucu seçildi
                </div>
              )}

              <div className="flex justify-between">
                <button onClick={() => setStep(1)} disabled={isJobActive} className={isJobActive ? "px-5 py-2.5 text-sm text-slate-600 cursor-not-allowed" : "px-5 py-2.5 text-sm text-slate-400 hover:text-white transition-colors"} title={isJobActive ? "İş devam ederken geri gidemezsiniz" : undefined}>← Geri</button>
                <button onClick={() => setStep(3)} disabled={selectedServers.length === 0}
                  className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl disabled:opacity-40 transition-colors">
                  Repo Seç →
                </button>
              </div>
            </div>
          )}

          {/* ── Adım 3: Yetkili Kullanıcı ─────────────────────────────────── */}
          {step === 3 && (
            <div className="space-y-5">
              <div>
                <h2 className="text-base font-semibold text-white">Yetkili Kullanıcı</h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Sistem güncellemesi <strong>root</strong> veya <strong>sudo</strong> yetkisi gerektirir.
                </p>
              </div>

              <div className="space-y-3">
                {/* Seçenek 1: Kayıtlı kimlik bilgileri */}
                <label className={`flex items-start gap-4 p-4 rounded-xl border-2 cursor-pointer transition-all ${
                  credMode === 'stored' ? 'border-green-500 bg-green-500/10' : 'border-slate-600 bg-white/[0.02] hover:border-slate-500'
                }`}>
                  <input type="radio" checked={credMode==='stored'} onChange={() => setCredMode('stored')}
                    className="accent-green-500 w-4 h-4 mt-0.5 flex-shrink-0" />
                  <div>
                    <div className="text-sm font-semibold text-white flex items-center gap-2">
                      Kayıtlı Kimlik Bilgilerini Kullan
                    </div>
                    <div className="text-xs text-slate-400 mt-1">
                      Her sunucu için kendi connection_config veya global credentials kullanılır.
                      <br/>Sunucularda sudo/root erişimi tanımlı olmalı.
                    </div>
                  </div>
                </label>

                {/* Seçenek 2: Özel kullanıcı */}
                <label className={`flex items-start gap-4 p-4 rounded-xl border-2 cursor-pointer transition-all ${
                  credMode === 'override' ? 'border-blue-500 bg-blue-500/10' : 'border-slate-600 bg-white/[0.02] hover:border-slate-500'
                }`}>
                  <input type="radio" checked={credMode==='override'} onChange={() => setCredMode('override')}
                    className="accent-blue-500 w-4 h-4 mt-0.5 flex-shrink-0" />
                  <div className="flex-1">
                    <div className="text-sm font-semibold text-white flex items-center gap-2">
                      Özel Yetkili Kullanıcı Belirt
                    </div>
                    <div className="text-xs text-slate-400 mt-1 mb-3">
                      Tüm seçili sunucularda bu kullanıcı ile bağlanılır (root veya sudo yetkili kullanıcı).
                    </div>

                    {credMode === 'override' && (
                      <div className="space-y-3 mt-2" onClick={e => e.stopPropagation()}>
                        <div>
                          <label className="text-xs text-slate-400 block mb-1">Kullanıcı Adı <span className="text-red-400">*</span></label>
                          <input value={overrideUser} onChange={e => setOverrideUser(e.target.value)}
                            placeholder="root veya sudo yetkili kullanıcı"
                            className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">SSH Şifresi</label>
                            <input type="password" value={overridePass} onChange={e => setOverridePass(e.target.value)}
                              placeholder="SSH şifresi"
                              className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                          </div>
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">
                              Sudo Şifresi
                              <span className="text-slate-500 ml-1">(root ise boş bırakın)</span>
                            </label>
                            <input type="password" value={overrideSudo} onChange={e => setOverrideSudo(e.target.value)}
                              placeholder="sudo şifresi (boşsa SSH şifresi kullanılır)"
                              className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                          </div>
                        </div>
                        <div className="flex items-start gap-1.5 bg-blue-500/10 border border-blue-500/20 rounded-lg px-3 py-2 text-xs text-blue-300">
                          <Lightbulb size={12} strokeWidth={2} className="flex-shrink-0 mt-0.5" />
                          <span>Root kullanıcı ise sudo şifresi boş bırakın.
                          Sudo kullanıcı ise SSH şifresi = sudo şifresi olabilir.</span>
                        </div>
                      </div>
                    )}
                  </div>
                </label>
              </div>

              {/* Yetki Yükseltme Yöntemi */}
              <div className="bg-white/[0.07]/30 border border-slate-600 rounded-xl p-4 space-y-3">
                <div>
                  <div className="text-sm font-semibold text-white">Yetki Yükseltme Yöntemi</div>
                  <div className="text-xs text-slate-400 mt-0.5">Komutları hangi yöntemle root yetkisiyle çalıştıracak?</div>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  {([
                    { key: 'sudo',   label: 'sudo',   desc: 'Standart Linux yetki yükseltme', icon: 'key' },
                    { key: 'dzdo',   label: 'dzdo',   desc: 'Centrify DirectControl (AD)',     icon: 'org' },
                    { key: 'direct', label: 'Direct', desc: 'Direkt root kullanıcı',           icon: 'RT' },
                  ] as const).map(m => (
                    <button key={m.key} onClick={() => setPrivMethod(m.key)}
                      className={`p-3 rounded-xl border text-left transition-all ${
                        privMethod === m.key
                          ? 'border-blue-500 bg-blue-600/15'
                          : 'border-slate-600 bg-white/[0.02] hover:border-slate-500'
                      }`}>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-slate-400">{m.icon}</span>
                        <span className={`text-sm font-bold ${privMethod === m.key ? 'text-white' : 'text-slate-300'}`}>
                          {m.label}
                        </span>
                      </div>
                      <div className="text-xs text-slate-500 mt-0.5">{m.desc}</div>
                    </button>
                  ))}
                </div>
                {privMethod === 'dzdo' && (
                    <div className="flex items-start gap-1.5 bg-blue-500/10 border border-blue-500/30 rounded-lg px-3 py-2 text-xs text-blue-300">
                      <Lightbulb size={12} strokeWidth={2} className="flex-shrink-0 mt-0.5" />
                      <span><strong>dzdo</strong>: AD hesabınız dzdo ile yetkili ise AD şifrenizi SSH şifresi olarak girin.</span>
                    </div>
                  )}
                  {privMethod === 'direct' && (
                    <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg px-3 py-2 text-xs text-yellow-300">
                      Direkt root kullanıcı — ekstra yetki yükseltme yapılmaz.
                    </div>
                  )}
              </div>

              {/* Özet */}
              <div className="bg-white/[0.07]/30 border border-slate-600 rounded-xl p-4">
                <div className="text-xs font-semibold text-slate-300 mb-2">Özet</div>
                <div className="text-xs text-slate-400 space-y-0.5">
                  <div>{selectedServers.length} sunucu seçildi</div>
                  {credMode === 'override' && overrideUser
                    ? <div className="text-green-400 font-medium">→ {overrideUser} ile {privMethod} kullanılacak</div>
                    : <div>→ Kayıtlı kimlik + <span className="text-blue-300 font-medium">{privMethod}</span></div>
                  }
                </div>
              </div>

              <div className="flex justify-between">
                <button onClick={() => setStep(2)} disabled={isJobActive} className={isJobActive ? "px-5 py-2.5 text-sm text-slate-600 cursor-not-allowed" : "px-5 py-2.5 text-sm text-slate-400 hover:text-white transition-colors"} title={isJobActive ? "İş devam ederken geri gidemezsiniz" : undefined}>← Geri</button>
                <button
                  onClick={() => setStep(4)}
                  disabled={credMode === 'override' && !overrideUser}
                  className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl disabled:opacity-40 transition-colors">
                  Repo Seç →
                </button>
              </div>
            </div>
          )}

          {/* ── Adım 4: Repo Seç ──────────────────────────────────────────── */}
          {step === 4 && (
            <div className="space-y-4">
              <div>
                <h2 className="text-base font-semibold text-white">Kaynak Repo</h2>
                <p className="text-xs text-slate-400 mt-0.5">Güncelleme kaynağını seçin. Local mirror kullanmak için seçin, yoksa sunucunun varsayılan repoları kullanılır.</p>
              </div>

              <div className="space-y-2">
                {/* Varsayılan seçenek */}
                <label className={`flex items-center gap-4 p-4 rounded-xl border-2 cursor-pointer transition-all ${
                  selectedRepo === null ? 'border-blue-500 bg-blue-600/10' : 'border-slate-600 hover:border-slate-500 bg-white/[0.02]'
                }`}>
                  <input type="radio" checked={selectedRepo===null} onChange={() => setSelectedRepo(null)} className="accent-blue-500 w-4 h-4 flex-shrink-0" />
                  <div>
                    <div className="flex items-center gap-1.5 text-sm font-semibold text-white">
                      <Globe size={14} strokeWidth={2} /> Varsayılan Repo
                    </div>
                    <div className="text-xs text-slate-400 mt-0.5">Sunucunun /etc/yum.repos.d/ veya apt sources.list kaynakları</div>
                  </div>
                </label>

                {/* Local repolar */}
                {filteredRepos.length > 0 ? (
                  filteredRepos.map(repo => (
                    <label key={repo.id} className={`flex items-center gap-4 p-4 rounded-xl border-2 cursor-pointer transition-all ${
                      selectedRepo===repo.id ? 'border-blue-500 bg-blue-600/10' : 'border-slate-600 hover:border-slate-500 bg-white/[0.02]'
                    }`}>
                      <input type="radio" checked={selectedRepo===repo.id} onChange={() => setSelectedRepo(repo.id)} className="accent-blue-500 w-4 h-4 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-semibold text-white">{repo.display_name}</div>
                        <div className="text-xs text-slate-400 mt-0.5">
                          {repo.repo_type.toUpperCase()} · Local mirror ·
                          <span className={`ml-1 ${repo.sync_status === 'synced' ? 'text-green-400' : 'text-yellow-400'}`}>
                            {repo.sync_status === 'synced'
                            ? <span className="inline-flex items-center gap-1"><CheckCircle2 size={11} strokeWidth={2} /> Güncel</span>
                            : <span className="inline-flex items-center gap-1"><AlertTriangle size={11} strokeWidth={2} /> Kısmi</span>}
                          </span>
                        </div>
                      </div>
                    </label>
                  ))
                ) : (
                  <div className="bg-white/[0.07]/30 border border-slate-600 rounded-xl p-4 text-center text-xs text-slate-400">
                    {selectedDistro
                      ? `${DISTRO_LIST.find(d=>d.key===selectedDistro)?.short} için senkronize local repo bulunamadı`
                      : 'Senkronize local repo yok'} — Varsayılan repo kullanılacak
                  </div>
                )}
              </div>

              <div className="flex justify-between">
                <button onClick={() => setStep(3)} disabled={isJobActive} className={isJobActive ? "px-5 py-2.5 text-sm text-slate-600 cursor-not-allowed" : "px-5 py-2.5 text-sm text-slate-400 hover:text-white transition-colors"} title={isJobActive ? "İş devam ederken geri gidemezsiniz" : undefined}>← Geri</button>
                <button onClick={() => setStep(5)}
                  className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl transition-colors">
                  Snapshot →
                </button>
              </div>
            </div>
          )}

          {/* ── Adım 5: VM Snapshot ───────────────────────────────────────── */}
          {step === 5 && (
            <div className="space-y-5">
              <div>
                <h2 className="flex items-center gap-2 text-base font-semibold text-white">
                  <Camera size={16} strokeWidth={1.8} /> VM Snapshot
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Güncelleme öncesi hypervisor üzerinden sanal makine snapshot'ı alınabilir (oVirt / vCenter).
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <button
                  onClick={() => setSnapshotMode('take')}
                  className={`p-5 rounded-xl border-2 text-left transition-all ${
                    snapshotMode === 'take'
                      ? 'border-cyan-500 bg-cyan-500/10'
                      : 'border-slate-600 bg-white/[0.02] hover:border-slate-500'
                  }`}
                >
                  <Camera size={32} strokeWidth={1.5} className="mb-2 text-slate-300" />
                  <div className="text-base font-bold text-white">Snapshot Al</div>
                  <div className="text-xs text-slate-400 mt-1">Güncelleme başlamadan önce VM yedeği oluştur</div>
                </button>
                <button
                  onClick={() => setSnapshotMode('skip')}
                  className={`p-5 rounded-xl border-2 text-left transition-all ${
                    snapshotMode === 'skip'
                      ? 'border-slate-400 bg-slate-600/20'
                      : 'border-slate-600 bg-white/[0.02] hover:border-slate-500'
                  }`}
                >
                  <div className="text-3xl mb-2">⏭️</div>
                  <div className="text-base font-bold text-white">Snapshot Alma</div>
                  <div className="text-xs text-slate-400 mt-1">Doğrudan güncellemeye geç (fiziksel sunucular için)</div>
                </button>
              </div>

              {snapshotMode === 'take' && (
                <div className="space-y-3">
                  <div className="text-xs font-semibold text-slate-300">Saklama Süresi</div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    {SNAPSHOT_RETENTIONS.map(r => (
                      <button
                        key={r.key}
                        onClick={() => setSnapshotRetention(r.key as typeof snapshotRetention)}
                        className={`p-3 rounded-xl border text-left transition-all ${
                          snapshotRetention === r.key
                            ? 'border-cyan-500 bg-cyan-500/10'
                            : 'border-slate-600 hover:border-slate-500 bg-white/[0.02]'
                        }`}
                      >
                        <div className="text-sm font-semibold text-white">{r.label}</div>
                        <div className="text-[10px] text-slate-400 mt-0.5">{r.desc}</div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {snapCapability && snapshotMode === 'take' && (
                <div className={`rounded-xl border px-4 py-3 text-sm ${
                  snapCapability.snapshot_ready > 0
                    ? 'border-cyan-500/30 bg-cyan-500/5 text-cyan-200'
                    : 'border-yellow-500/30 bg-yellow-500/5 text-yellow-200'
                }`}>
                  <div className="font-medium">
                    {snapCapability.snapshot_ready}/{snapCapability.total} sunucu snapshot almaya hazır
                  </div>
                  {snapCapability.snapshot_missing > 0 && (
                    <ul className="mt-2 space-y-1 text-xs opacity-90 max-h-32 overflow-y-auto">
                      {snapCapability.servers.filter(s => !s.can_snapshot).map(s => (
                        <li key={s.server_id}>
                          ⊘ {s.server_name || `#${s.server_id}`}: {s.reason || 'VM bağlantısı yok'}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <div className="flex justify-between">
                <button onClick={() => setStep(4)} disabled={isJobActive} className={isJobActive ? "px-5 py-2.5 text-sm text-slate-600 cursor-not-allowed" : "px-5 py-2.5 text-sm text-slate-400 hover:text-white transition-colors"} title={isJobActive ? "İş devam ederken geri gidemezsiniz" : undefined}>← Geri</button>
                <button onClick={() => setStep(6)}
                  className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl transition-colors">
                  Güncelleme Modu →
                </button>
              </div>
            </div>
          )}

          {/* ── Adım 6: Güncelleme Modu ───────────────────────────────────── */}
          {step === 6 && (
            <div className="space-y-5">
              <div>
                <h2 className="text-base font-semibold text-white">Güncelleme Modu</h2>
                <p className="text-xs text-slate-400 mt-0.5">Ne tür güncelleme yapılacak?</p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {UPDATE_TYPES.map(t => (
                  <button key={t.key} onClick={() => setUpdateType(t.key)}
                    className={`p-5 rounded-xl border-2 text-left transition-all ${
                      updateType === t.key ? t.color + ' border-2' : 'border-slate-600 bg-white/[0.02] hover:border-slate-500 hover:bg-white/[0.04]'
                    }`}>
                    <div className="text-xs font-bold text-slate-400 mb-1">{t.icon}</div>
                    <div className="text-base font-bold text-white">{t.label}</div>
                    <div className="text-xs text-slate-400 mt-1">{t.desc}</div>
                  </button>
                ))}
              </div>

              {/* Özet + Plan adı */}
              {updateType && (
                <div className="bg-white/[0.04] border border-slate-600 rounded-xl p-4 space-y-3">
                  <div className="text-xs font-semibold text-slate-300 mb-2">Plan Özeti</div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                    <div className="bg-white/[0.07]/50 rounded-lg p-2 text-center">
                      <div className="text-xs font-bold text-slate-400">{DISTRO_LIST.find(d=>d.key===selectedDistro)?.icon}</div>
                      <div className="text-slate-400 mt-0.5">{DISTRO_LIST.find(d=>d.key===selectedDistro)?.short}</div>
                    </div>
                    <div className="bg-white/[0.07]/50 rounded-lg p-2 text-center">
                      <div className="text-lg font-bold text-white">{selectedServers.length}</div>
                      <div className="text-slate-400">Sunucu</div>
                    </div>
                    <div className="bg-white/[0.07]/50 rounded-lg p-2 text-center">
                      <div className="text-xs font-bold text-blue-400">{UPDATE_TYPES.find(t=>t.key===updateType)?.icon}</div>
                      <div className="text-slate-400 mt-0.5">{UPDATE_TYPES.find(t=>t.key===updateType)?.label}</div>
                    </div>
                    <div className="bg-white/[0.07]/50 rounded-lg p-2 text-center">
                      <div className="text-xs text-white font-medium">{selectedRepo ? 'Local' : 'Varsayılan'}</div>
                      <div className="text-slate-400">Repo</div>
                    </div>
                  </div>
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">Plan Adı (isteğe bağlı)</label>
                    <input value={planName} onChange={e => setPlanName(e.target.value)}
                      placeholder={`${DISTRO_LIST.find(d=>d.key===selectedDistro)?.short || 'Linux'} ${UPDATE_TYPES.find(t=>t.key===updateType)?.label} — ${new Date().toLocaleDateString('tr-TR')}`}
                      className="w-full bg-white/[0.07] text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                  </div>
                </div>
              )}

              {updateType === 'kernel' && (
                <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl px-4 py-3 text-sm text-yellow-300">
                  Kernel güncellemesi sonrası sunucular yeniden başlatılmalıdır.
                </div>
              )}

              {/* Güncellemeleri Kontrol Et */}
              {updateType && (
                <div className="border border-white/[0.06] rounded-xl overflow-hidden">
                  <div className="flex items-center justify-between px-4 py-3 bg-white/[0.04] border-b border-white/[0.06]">
                    <div className="text-sm font-semibold text-white">Mevcut Güncellemeler</div>
                    <button
                      onClick={async () => {
                        setChecking(true)
                        try {
                          const body: any = { server_ids: selectedServers, update_type: updateType }
                          if (selectedRepo) body.repo_id = selectedRepo
                          if (credMode === 'override' && overrideUser) {
                            body.override_username = overrideUser
                            body.override_password = overridePass || undefined
                            body.override_sudo_password = overrideSudo || overridePass || undefined
                            body.priv_method = privMethod
                          }
                          const r = await fetch(`${API}/check`, {
                            method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(body),
                          })
                          if (r.ok) setCheckResult(await r.json())
                        } finally { setChecking(false) }
                      }}
                      disabled={checking}
                      className="px-3 py-1.5 text-xs bg-slate-600 hover:bg-slate-500 text-white rounded-lg transition-colors disabled:opacity-40 flex items-center gap-1.5"
                    >
                      {checking
                        ? <><div className="w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />Kontrol ediliyor...</>
                        : 'Sunucularda Kontrol Et'}
                    </button>
                  </div>

                  {Object.keys(checkResult).length === 0 && !checking && (
                    <div className="px-4 py-6 text-center text-slate-500 text-xs">
                      Güncellemeleri görmek için "Sunucularda Kontrol Et" butonuna tıklayın
                    </div>
                  )}

                  {checking && (
                    <div className="px-4 py-6 text-center">
                      <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
                      <div className="text-xs text-slate-400">SSH ile sunucular kontrol ediliyor...</div>
                    </div>
                  )}

                  {Object.keys(checkResult).length > 0 && !checking && (
                    <div className="divide-y divide-white/[0.04] max-h-[50vh] overflow-y-auto">
                  {Object.entries(checkResult).map(([sid, data]: [string, any]) => (
                    <div key={sid} className="px-4 py-3">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-sm font-medium text-white">{data.server_name}</span>
                        <div className="flex items-center gap-2 text-xs">
                          {data.security_count > 0 && (
                            <span className="inline-flex items-center gap-1 bg-red-500/20 text-red-300 border border-red-500/30 px-2 py-0.5 rounded-md">
                              <Lock size={10} strokeWidth={2} /> {data.security_count}
                            </span>
                          )}
                          {data.kernel_count > 0 && (
                            <span className="bg-blue-500/20 text-blue-300 border border-blue-500/30 px-2 py-0.5 rounded-full">
                              kernel: {data.kernel_count}
                            </span>
                          )}
                          <span className="text-slate-400">{data.count} toplam</span>
                        </div>
                      </div>
                      {data.count === 0 ? (
                        <div className="text-xs text-green-400">✓ Güncel, güncelleme yok</div>
                      ) : updateType === 'custom' && data.packages?.length > 0 ? (
                        /* Custom mod: checkbox listesi */
                        <div className="space-y-1 mt-2">
                          <div className="flex items-center gap-2 mb-2">
                            <input value={pkgSearch} onChange={e => setPkgSearch(e.target.value)}
                              placeholder="Paket ara..." className="flex-1 bg-cyber-card text-white text-xs px-2 py-1 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                            <button onClick={() => {
                              const allNames = data.packages.map((p: any) => p.name)
                              if (allNames.every((n: string) => selectedPkgs.has(n))) {
                                setSelectedPkgs(prev => { const next = new Set(prev); allNames.forEach((n: string) => next.delete(n)); return next })
                              } else {
                                setSelectedPkgs(prev => new Set([...prev, ...allNames]))
                              }
                            }} className="text-xs text-blue-400 hover:text-blue-300 px-2 py-1 hover:bg-white/[0.06] rounded transition-colors">
                              Tümü
                            </button>
                            <span className="text-xs text-slate-500">{selectedPkgs.size} seçili</span>
                          </div>
                          <div className="max-h-72 overflow-y-auto space-y-0.5 pr-1">
                            {data.packages
                              .filter((p: any) => !pkgSearch || p.name.toLowerCase().includes(pkgSearch.toLowerCase()))
                              .map((p: any, i: number) => (
                              <label key={i} className={`flex items-center gap-2 px-2 py-1 rounded cursor-pointer hover:bg-white/[0.03] ${selectedPkgs.has(p.name) ? 'bg-blue-600/10' : ''}`}>
                                <input type="checkbox" checked={selectedPkgs.has(p.name)}
                                  onChange={() => setSelectedPkgs(prev => { const next = new Set(prev); next.has(p.name) ? next.delete(p.name) : next.add(p.name); return next })}
                                  className="accent-blue-500 w-3.5 h-3.5 flex-shrink-0" />
                                <span className={`text-xs font-mono ${p.is_security ? 'text-red-300' : p.is_kernel ? 'text-blue-300' : 'text-slate-200'}`}>
                                  {p.is_security && <span className="text-[9px] font-bold text-red-400 mr-1">SEC</span>}{p.is_kernel && <span className="text-[9px] font-bold text-blue-400 mr-1">KRN</span>}{p.name}
                                </span>
                                {p.new_version && <span className="text-[10px] text-slate-500 ml-auto">{p.new_version.split('-')[0]}</span>}
                              </label>
                            ))}
                          </div>
                        </div>
                      ) : data.packages?.length > 0 ? (
                        /* Normal mod: badge listesi */
                        <div className="flex flex-wrap gap-1 mt-1">
                          {data.packages.slice(0, 12).map((p: any, i: number) => (
                            <span key={i} className={`text-[11px] px-1.5 py-0.5 rounded font-mono ${
                              p.is_security ? 'bg-red-500/15 text-red-300' :
                              p.is_kernel   ? 'bg-blue-500/15 text-blue-300' :
                              'bg-white/[0.07] text-slate-300'
                            }`}>
                              {p.name}
                              {p.new_version ? <span className="text-slate-500 ml-1">→{p.new_version.split('-')[0]}</span> : null}
                            </span>
                          ))}
                          {data.packages.length > 12 && (
                            <span className="text-[11px] text-slate-500 px-1.5 py-0.5">+{data.packages.length - 12} daha</span>
                          )}
                        </div>
                      ) : null}
                      {data.packages?.[0]?.error && (
                        <div className="text-xs text-red-400 mt-1">SSH Hatası: {data.packages[0].error}</div>
                      )}
                    </div>
                  ))}
                    </div>
                  )}
                </div>
              )}

              <div className="flex justify-between">
                <button onClick={() => setStep(5)} disabled={isJobActive} className={isJobActive ? "px-5 py-2.5 text-sm text-slate-600 cursor-not-allowed" : "px-5 py-2.5 text-sm text-slate-400 hover:text-white transition-colors"} title={isJobActive ? "İş devam ederken geri gidemezsiniz" : undefined}>← Geri</button>
                <button
                  onClick={handleCreatePlan}
                  disabled={!updateType || (updateType === 'custom' && selectedPkgs.size === 0)}
                  className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl disabled:opacity-40 transition-colors"
                >
                  {updateType === 'custom'
                    ? selectedPkgs.size > 0 ? `${selectedPkgs.size} Paket — AI Analiz →` : 'Paket Seçin'
                    : 'AI Analiz →'}
                </button>
              </div>
            </div>
          )}

          {/* ── Adım 7: AI Analiz ─────────────────────────────────────────── */}
          {step === 7 && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-semibold text-white">AI Ön Analiz</h2>
                <span className="text-xs text-slate-500 italic">İsteğe bağlı — atlayabilirsiniz</span>
              </div>

              {/* AI başlat veya yükleniyor */}
              {!aiAnalysis && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className={`border rounded-xl p-5 text-center space-y-3 ${analyzing ? 'border-blue-500/30 bg-blue-500/5' : 'border-slate-600 bg-white/[0.02]'}`}>
                    <div className="text-xl font-bold text-blue-400">{analyzing ? '...' : 'AI'}</div>
                    {analyzing ? (
                      <>
                        <div className="w-10 h-10 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
                        <div className="text-sm text-blue-300 animate-pulse">Analiz yapılıyor...</div>
                        <div className="text-xs text-slate-500">SSH kontrol + AI değerlendirme</div>
                      </>
                    ) : (
                      <>
                        <div className="text-sm font-medium text-white">AI Analiz Yap</div>
                        <div className="text-xs text-slate-400">Risk değerlendirmesi, reboot tahmini, önerilen sıra</div>
                        <button onClick={handleAnalyze}
                          className="w-full py-2 bg-cyan-700 hover:bg-cyan-600 text-white font-semibold text-sm rounded-lg transition-colors">
                          Analizi Başlat
                        </button>
                      </>
                    )}
                  </div>
                  <div className="border border-slate-600 bg-white/[0.02] rounded-xl p-5 text-center space-y-3 flex flex-col justify-center">
                    <div className="text-3xl">⏭️</div>
                    <div className="text-sm font-medium text-white">Analiz Olmadan Devam</div>
                    <div className="text-xs text-slate-400">Direkt onay adımına geç</div>
                    <button onClick={() => { setCurrentPlan(currentPlan); setStep(8) }}
                      disabled={!currentPlan}
                      className="w-full py-2 bg-slate-600 hover:bg-slate-500 text-white font-semibold text-sm rounded-lg transition-colors disabled:opacity-40">
                      Atla & Onayla →
                    </button>
                  </div>
                </div>
              )}

              {/* AI sonucu — kart tabanlı render */}
              {aiAnalysis && (
                <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-xl overflow-hidden">
                  <div className="flex items-center justify-between px-4 py-3 border-b border-cyan-500/15 bg-cyan-500/5">
                    <div className="flex items-center gap-2 text-xs font-semibold text-cyan-400">
                      AI Analiz Sonucu
                    </div>
                    <button onClick={() => setAiAnalysis('')}
                      className="text-slate-500 hover:text-slate-300 text-xs transition-colors">
                      Yenile
                    </button>
                  </div>
                  <div className="p-4 max-h-80 overflow-y-auto">
                    <AiMarkdown text={aiAnalysis} />
                  </div>
                </div>
              )}

              <div className="flex justify-between">
                <button onClick={() => setStep(6)} disabled={isJobActive} className={isJobActive ? "px-5 py-2.5 text-sm text-slate-600 cursor-not-allowed" : "px-5 py-2.5 text-sm text-slate-400 hover:text-white transition-colors"} title={isJobActive ? "İş devam ederken geri gidemezsiniz" : undefined}>← Geri</button>
                <button onClick={() => setStep(8)}
                  className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl transition-colors">
                  {aiAnalysis ? 'İncele & Onayla →' : 'Onayla →'}
                </button>
              </div>
            </div>
          )}

          {/* ── Adım 8: Onay ──────────────────────────────────────────────── */}
          {step === 8 && currentPlan && (
            <div className="space-y-5">
              <h2 className="text-base font-semibold text-white">Güncellemeyi Onayla</h2>

              <div className="bg-white/[0.07]/50 rounded-xl p-5">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                  <div className="text-center">
                    <div className="text-xs font-bold text-slate-400">{DISTRO_LIST.find(d=>d.key===selectedDistro)?.icon}</div>
                    <div className="text-slate-400 text-xs">{DISTRO_LIST.find(d=>d.key===selectedDistro)?.label}</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-white">{selectedServers.length}</div>
                    <div className="text-slate-400 text-xs">Sunucu</div>
                  </div>
                  <div className="text-center">
                    <div className="text-xs font-bold text-blue-400">{UPDATE_TYPES.find(t=>t.key===updateType)?.icon}</div>
                    <div className="text-slate-400 text-xs">{UPDATE_TYPES.find(t=>t.key===updateType)?.label}</div>
                  </div>
                  <div className="text-center">
                    <div className="text-sm font-medium text-white">{selectedRepo ? 'Local' : 'Varsayılan'}</div>
                    <div className="text-slate-400 text-xs">Repo</div>
                  </div>
                  <div className="text-center">
                    <div className="flex items-center justify-center gap-1 text-sm font-medium text-white">
                      {snapshotMode === 'take'
                        ? <><Camera size={12} strokeWidth={2} /> {SNAPSHOT_RETENTIONS.find(r => r.key === snapshotRetention)?.label || snapshotRetention}</>
                        : 'Yok'}
                    </div>
                    <div className="text-slate-400 text-xs">Snapshot</div>
                  </div>
                  <div className="text-center">
                    <div className="text-sm font-medium text-white">
                      {credMode === 'override' && overrideUser ? overrideUser : 'Kayıtlı'}
                    </div>
                    <div className="text-slate-400 text-xs">Kullanıcı</div>
                  </div>
                  <div className="text-center">
                    <div className="text-sm font-medium text-white">
                      {privMethod === 'sudo' ? 'sudo' : privMethod === 'dzdo' ? 'dzdo' : 'direct'}
                    </div>
                  </div>
                  {updateType === 'custom' && (
                    <div className="text-center">
                      <div className="text-lg font-bold text-cyan-300">{selectedPkgs.size}</div>
                      <div className="text-slate-400 text-xs">Seçili paket</div>
                    </div>
                  )}
                </div>
              </div>

              {updateType === 'kernel' && (
                <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl px-4 py-3 text-sm text-yellow-300">
                  Kernel güncellemesi sonrası reboot gerekecek — bunu önceden planlayın.
                </div>
              )}

              {aiAnalysis && (
                <details className="bg-white/[0.07]/30 border border-slate-600 rounded-xl">
                  <summary className="px-4 py-3 text-sm text-cyan-400 cursor-pointer select-none">
                    AI Analiz Özetini Göster
                  </summary>
                  <div className="px-4 pb-4 text-xs text-slate-300 leading-relaxed whitespace-pre-wrap border-t border-slate-600 pt-3 mt-0">
                    {aiAnalysis}
                  </div>
                </details>
              )}

              <div className="flex justify-between">
                <button onClick={() => setStep(7)} disabled={isJobActive} className={isJobActive ? "px-5 py-2.5 text-sm text-slate-600 cursor-not-allowed" : "px-5 py-2.5 text-sm text-slate-400 hover:text-white transition-colors"} title={isJobActive ? "İş devam ederken geri gidemezsiniz" : undefined}>← Geri</button>
                <button onClick={handleRun}
                  className="px-8 py-3 bg-green-700 hover:bg-green-600 text-white font-bold text-sm rounded-xl transition-colors flex items-center gap-2">
                  ✓ Onayla ve Güncellemeyi Başlat
                </button>
              </div>
            </div>
          )}

          {/* ── Adım 9: Canlı İzleme ──────────────────────────────────────── */}
          {step === 9 && currentPlan && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-semibold text-white">Canlı İzleme</h2>
                <span className={`text-sm font-medium flex items-center gap-1.5 ${STATUS_COLOR[currentPlan.status]}`}>
                  {currentPlan.status === 'running' && <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse inline-block" />}
                  {STATUS_LABEL[currentPlan.status]}
                </span>
              </div>

              <div>
                <div className="flex justify-between text-xs text-slate-400 mb-1">
                  <span>{currentPlan.completed_servers} / {currentPlan.total_servers} sunucu</span>
                  <span>{Math.round(currentPlan.completed_servers*100/Math.max(currentPlan.total_servers,1))}%</span>
                </div>
                <div className="bg-white/[0.07] rounded-full h-2.5">
                  <div className="bg-blue-500 h-2.5 rounded-full transition-all duration-500"
                    style={{ width: `${Math.round(currentPlan.completed_servers*100/Math.max(currentPlan.total_servers,1))}%` }} />
                </div>
              </div>

              {/* Sunucu satırları — tıklanabilir, detay açılır */}
              <div className="space-y-2">
                {planJobs.map(j => (
                  <div key={j.id} className="bg-white/[0.04] rounded-xl overflow-hidden border border-white/[0.06]/50">
                    {/* Satır başlığı — tıkla */}
                    <button
                      className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/[0.03] transition-colors text-left"
                      onClick={() => setExpandedJob(expandedJob === j.id ? null : j.id)}
                    >
                      <span className={`text-xs font-medium w-20 flex-shrink-0 ${STATUS_COLOR[j.status]}`}>
                        {(j.status==='running'||j.status==='pending') && <span className="inline-block w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse mr-1" />}
                        {STATUS_LABEL[j.status]}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-white">{j.server_name}</div>
                        <div className="text-xs text-slate-400 flex gap-2">
                          <span>{j.server_ip}</span>
                          {j.os_type && <span className="text-blue-400">{j.os_type.toUpperCase()} {j.os_version}</span>}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        {j.packages_updated.length > 0 && <span className="text-xs text-green-400">{j.packages_updated.length} paket</span>}
                        {j.reboot_required && <span className="text-xs text-yellow-400">REBOOT</span>}
                        {j.snapshot?.status === 'active' && (
                          <span className="inline-flex items-center gap-1 text-xs text-cyan-400" title={j.snapshot.snapshot_name}>
                            <Camera size={11} strokeWidth={2} /> Snap
                          </span>
                        )}
                        {j.snapshot?.status === 'failed' && (
                          <span className="inline-flex items-center gap-1 text-xs text-orange-400" title={j.snapshot.error_message || ''}>
                            <Camera size={11} strokeWidth={2} /> Hata
                          </span>
                        )}
                        <span className="text-slate-500 text-xs">{expandedJob === j.id ? '▲' : '▼'}</span>
                      </div>
                    </button>

                    {/* Genişletilmiş detay */}
                    {expandedJob === j.id && (
                      <div className="px-4 pb-4 border-t border-white/[0.05] space-y-3 pt-3">
                    {j.status === 'completed' && (
                      <PackageList job={j} planId={currentPlan?.id || 0} />
                    )}
                    {/* Yeniden çalıştır butonu */}
                    {['completed','failed','partial'].includes(j.status) && (
                      <button
                        onClick={async () => {
                          if (!currentPlan) return
                          if (!confirm(`"${j.server_name}" sunucusunda güncelleme yeniden çalıştırılsın mı?`)) return
                          const r = await fetch(`${API}/plans/${currentPlan.id}/jobs/${j.id}/rerun`, { method: 'POST' })
                          if (r.ok) {
                            const [pr, jr] = await Promise.all([
                              fetch(`${API}/plans/${currentPlan.id}`),
                              fetch(`${API}/plans/${currentPlan.id}/jobs`),
                            ])
                            if (pr.ok) setCurrentPlan(await pr.json())
                            if (jr.ok) setPlanJobs(await jr.json())
                          } else alert((await r.json()).detail || 'Hata')
                        }}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white/[0.07] hover:bg-slate-600 text-slate-200 border border-slate-600 rounded-lg transition-colors w-full justify-center mt-1"
                      >
                        ↻ Bu Sunucuda Yeniden Çalıştır
                      </button>
                    )}
                        {j.packages_to_update.length > 0 && j.packages_updated.length < j.packages_to_update.length && (
                          <div className="text-xs text-slate-400">
                            Planlanan: {j.packages_to_update.length} paket · Kurulan: {j.packages_updated.length}
                          </div>
                        )}
                    {/* Log — running job'da canlı, diğerlerinde statik */}
                    {(j.log || j.status === 'running' || j.status === 'pending') && (
                      <LiveJobLog
                        job={j}
                        planId={currentPlan?.id || 0}
                        onAnalyze={async () => {
                          if (!currentPlan) return
                          setLiveAiLoading(j.id)
                          const r = await fetch(`${API}/plans/${currentPlan.id}/jobs/${j.id}/analyze-error`, { method: 'POST' })
                          if (r.ok) { const d = await r.json(); setLiveJobAi(prev => ({...prev, [j.id]: d.analysis})) }
                          setLiveAiLoading(null)
                        }}
                        analyzing={liveAiLoading === j.id}
                        aiResult={liveJobAi[j.id] || null}
                      />
                    )}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {currentPlan.ai_summary && (
                <div className="bg-green-500/5 border border-green-500/20 rounded-xl p-4">
                  <div className="text-xs font-semibold text-green-400 mb-2">AI Güncelleme Özeti</div>
                  <AiMarkdown text={currentPlan.ai_summary} />
                </div>
              )}

              {['completed','failed','partial'].includes(currentPlan.status) && (
                <button onClick={resetWizard}
                  className="w-full py-3 bg-white/[0.07] hover:bg-slate-600 text-white text-sm font-medium rounded-xl transition-colors">
                  ← Plan Listesine Dön
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── REBOOT BEKLEYEN SUNUCULAR ──────────────────────────────────────── */}
      {!showWizard && <RebootPanel loadPlans={loadPlans} />}

      {/* ── GEÇMİŞ ──────────────────────────────────────────────────────── */}
      {!showWizard && (
        <div className="bg-cyber-card border border-white/[0.06] rounded-[10px] overflow-hidden">
          <div className="px-4 py-3 border-b border-white/[0.06] flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white">Güncelleme Geçmişi</h2>
            <button onClick={loadPlans} className="text-xs text-slate-400 hover:text-white px-2 py-1 hover:bg-white/[0.06] rounded transition-colors">↻ Yenile</button>
          </div>
          {plans.length === 0 ? (
            <div className="py-16 text-center space-y-3">
              <div className="text-slate-400 text-sm">Henüz güncelleme yapılmadı</div>
              <button onClick={() => setShowWizard(true)}
                className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold rounded-xl transition-colors">
                İlk Güncellemeyi Başlat
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[560px]">
              <thead>
                <tr className="bg-white/[0.07]/50 border-b border-slate-600">
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-300 uppercase tracking-wide">Plan</th>
                  <th className="text-left px-3 py-2.5 text-xs font-semibold text-slate-300 uppercase tracking-wide">Mod</th>
                  <th className="text-left px-3 py-2.5 text-xs font-semibold text-slate-300 uppercase tracking-wide">Durum</th>
                  <th className="text-center px-3 py-2.5 text-xs font-semibold text-slate-300 uppercase tracking-wide">İlerleme</th>
                  <th className="text-left px-3 py-2.5 text-xs font-semibold text-slate-300 uppercase tracking-wide w-[130px]">İşlem</th>
                </tr>
              </thead>
              <tbody>
                {plans.map(p => (
                  <PlanRow key={p.id} plan={p} onView={setViewPlan} onDelete={handleDeletePlan} onResume={handleResumePlan} onCancel={handleCancelPlan} onRerunFailed={handleRerunFailed} />
                ))}
              </tbody>
            </table>
            </div>
          )}
        </div>
      )}

      {viewPlan && <PlanDetailModal plan={viewPlan} onClose={() => setViewPlan(null)} />}
    </div>
  )
}

export default SystemUpdate
