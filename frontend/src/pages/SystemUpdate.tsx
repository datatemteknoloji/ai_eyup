import React, { useState, useEffect, useCallback } from 'react'

// ─── Types ────────────────────────────────────────────────────────────────────
interface ServerItem {
  id: number; name: string; ip: string
  os_type: string|null; os_release_id: string; os_version_id: string
  os_version: string; kernel_version: string; status: string
  has_os_info: boolean
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
  started_at: string|null; completed_at: string|null
}
interface UpdatePlan {
  id: number; name: string; update_type: string; status: string
  total_servers: number; completed_servers: number
  ai_analysis: string|null; ai_summary: string|null
  server_ids: number[]; created_at: string
  started_at: string|null; completed_at: string|null
}

// ─── Constants ────────────────────────────────────────────────────────────────
const API = '/api/v1/updates'

const DISTRO_LIST = [
  { key: 'rhel',   label: 'Red Hat Enterprise Linux', short: 'RHEL',   icon: '🔴', color: 'border-red-500/60 bg-red-500/10',    match: ['rhel'] },
  { key: 'oel',    label: 'Oracle Enterprise Linux',  short: 'OEL',    icon: '🟠', color: 'border-orange-500/60 bg-orange-500/10', match: ['ol', 'oel'] },
  { key: 'rocky',  label: 'Rocky Linux',              short: 'Rocky',  icon: '🟢', color: 'border-green-500/60 bg-green-500/10',  match: ['rocky'] },
  { key: 'ubuntu', label: 'Ubuntu',                   short: 'Ubuntu', icon: '🟡', color: 'border-yellow-500/60 bg-yellow-500/10', match: ['ubuntu'] },
  { key: '',       label: 'Tüm Dağıtımlar',           short: 'Tümü',   icon: '🌐', color: 'border-slate-500/60 bg-slate-700/30',  match: [] },
]

const UPDATE_TYPES = [
  { key: 'security', label: 'Güvenlik',    desc: 'Yalnızca CVE & güvenlik yamaları',         icon: '🔒', color: 'border-orange-500 bg-orange-500/10 text-orange-300' },
  { key: 'kernel',   label: 'Kernel',      desc: 'Linux çekirdeği güncellemesi',              icon: '⚡', color: 'border-purple-500 bg-purple-500/10 text-purple-300' },
  { key: 'all',      label: 'Tüm Paketler',desc: 'Sistemdeki tüm paketleri güncelle',         icon: '⬆️', color: 'border-blue-500   bg-blue-500/10   text-blue-300'   },
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
const STEP_NAMES = ['Distro', 'Sunucular', 'Yetkili Kullanıcı', 'Repo', 'Güncelleme Modu', 'AI Analiz', 'Onayla', 'İzle']

const Steps = ({ current }: { current: number }) => (
  <div className="flex items-center gap-1 mb-8 flex-wrap">
    {STEP_NAMES.map((s, i) => (
      <React.Fragment key={i}>
        <div className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap ${
          i+1 === current ? 'bg-blue-600 text-white' :
          i+1 < current   ? 'bg-green-700/40 text-green-300' : 'bg-slate-800 text-slate-500'
        }`}>{i+1 < current ? '✓ ' : `${i+1}. `}{s}</div>
        {i < STEP_NAMES.length-1 && (
          <div className={`flex-1 h-0.5 min-w-[6px] ${i+1 < current ? 'bg-green-600' : 'bg-slate-700'}`} />
        )}
      </React.Fragment>
    ))}
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
    <div className="border border-slate-700 rounded-xl overflow-hidden">
      <div className="bg-slate-800/80 px-3 py-2 flex gap-2 border-b border-slate-700 flex-wrap items-center">
        <input value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Sunucu veya IP ara..."
          className="flex-1 min-w-[160px] bg-slate-700 text-white text-sm px-3 py-1.5 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
        <button onClick={() => onChange(filtered.map(s => s.id))}
          className="text-xs text-blue-400 hover:text-blue-300 px-2 py-1 hover:bg-slate-700 rounded">Tümü</button>
        <button onClick={() => onChange(filtered.filter(s => s.status === 'ONLINE').map(s => s.id))}
          className="text-xs text-green-400 hover:text-green-300 px-2 py-1 hover:bg-slate-700 rounded">Aktifler</button>
        <button onClick={() => onChange([])}
          className="text-xs text-slate-400 hover:text-slate-300 px-2 py-1 hover:bg-slate-700 rounded">Temizle</button>
        <span className="text-xs text-slate-500 ml-auto">{selected.length} / {servers.length} seçili</span>
      </div>
      <div className="max-h-64 overflow-y-auto divide-y divide-slate-700/40">
        {filtered.map(srv => (
          <label key={srv.id}
            className={`flex items-center gap-3 px-4 py-2.5 cursor-pointer transition-colors hover:bg-slate-700/30 ${selected.includes(srv.id) ? 'bg-blue-600/10' : ''}`}>
            <input type="checkbox" checked={selected.includes(srv.id)} onChange={() => toggle(srv.id)}
              className="accent-blue-500 w-4 h-4 flex-shrink-0" />
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${srv.status === 'ONLINE' ? 'bg-green-400' : 'bg-slate-500'}`} />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-white truncate">{srv.name}</div>
              <div className="flex items-center gap-2 text-xs flex-wrap">
                <span className="text-slate-400 font-mono">{srv.ip}</span>
                {srv.os_release_id ? (
                  <span className="text-blue-400 font-medium">
                    {srv.os_release_id.toUpperCase()} {srv.os_version_id}
                  </span>
                ) : srv.os_version ? (
                  <span className="text-slate-300 truncate max-w-[200px]">{srv.os_version}</span>
                ) : (
                  <span className="text-yellow-500 text-[10px]">⚠ OS bilgisi yok</span>
                )}
                {srv.kernel_version && (
                  <span className="text-slate-500 font-mono truncate max-w-[160px]">⚙ {srv.kernel_version}</span>
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
const PlanRow = ({ plan, onView, onDelete }: {
  plan: UpdatePlan; onView: (p: UpdatePlan) => void; onDelete: (id: number) => void
}) => {
  const isRunning = plan.status === 'running' || plan.status === 'ai_analyzing'
  const ut = UPDATE_TYPES.find(t => t.key === plan.update_type)
  return (
    <tr className="border-b border-slate-700/50 hover:bg-slate-800/40 transition-colors">
      <td className="px-4 py-3">
        <div className="text-sm font-medium text-white">{plan.name}</div>
        <div className="text-xs text-slate-500">{fmtDate(plan.created_at)}</div>
      </td>
      <td className="px-3 py-3 text-xs whitespace-nowrap">{ut?.icon} {ut?.label}</td>
      <td className="px-3 py-3 whitespace-nowrap">
        <span className={`text-xs font-medium flex items-center gap-1 ${STATUS_COLOR[plan.status]}`}>
          {isRunning && <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse inline-block" />}
          {STATUS_LABEL[plan.status] || plan.status}
        </span>
      </td>
      <td className="px-3 py-3 text-center">
        <div className="text-sm text-white">{plan.completed_servers}/{plan.total_servers}</div>
        {plan.total_servers > 0 && (
          <div className="w-full bg-slate-700 rounded-full h-1 mt-1">
            <div className="bg-blue-500 h-1 rounded-full transition-all"
              style={{ width: `${Math.round(plan.completed_servers*100/plan.total_servers)}%` }} />
          </div>
        )}
      </td>
      <td className="px-3 py-3">
        <div className="flex gap-1">
          <button onClick={() => onView(plan)}
            className="px-2.5 py-1 text-xs bg-blue-700 hover:bg-blue-600 text-white rounded-lg transition-colors">
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
  const [jobs, setJobs] = useState<UpdateJob[]>([])
  const [sel,  setSel]  = useState<UpdateJob|null>(null)

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
      <div className="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-5xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700 flex-shrink-0">
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
          <div className="w-64 border-r border-slate-700 overflow-y-auto flex-shrink-0">
            {plan.ai_analysis && (
              <div className="p-3 border-b border-slate-700 bg-cyan-500/5">
                <div className="text-xs font-semibold text-cyan-400 mb-1">🤖 AI Analiz</div>
                <div className="text-xs text-slate-300 line-clamp-5 leading-relaxed">{plan.ai_analysis}</div>
              </div>
            )}
            {plan.ai_summary && (
              <div className="p-3 border-b border-slate-700 bg-green-500/5">
                <div className="text-xs font-semibold text-green-400 mb-1">✅ AI Özet</div>
                <div className="text-xs text-slate-300 leading-relaxed">{plan.ai_summary}</div>
              </div>
            )}
            {jobs.map(j => (
              <button key={j.id} onClick={() => setSel(j)}
                className={`w-full text-left px-4 py-3 hover:bg-slate-700/30 border-b border-slate-700/30 transition-colors ${sel?.id === j.id ? 'bg-blue-600/10' : ''}`}>
                <div className="flex items-center gap-2">
                  <span className={`text-xs ${STATUS_COLOR[j.status]}`}>
                    {(j.status==='running'||j.status==='pending') && <span className="inline-block w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse mr-1" />}
                    {STATUS_LABEL[j.status]}
                  </span>
                  {j.reboot_required && <span className="text-yellow-400 text-xs">⚠️</span>}
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
                  <div className="bg-slate-700/50 rounded-lg p-3"><div className="text-slate-400">Başlangıç</div><div className="text-white">{fmtDate(sel.started_at)}</div></div>
                  <div className="bg-slate-700/50 rounded-lg p-3"><div className="text-slate-400">Bitiş</div><div className="text-white">{fmtDate(sel.completed_at)}</div></div>
                </div>
                {sel.reboot_required && (
                  <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl px-4 py-3 text-sm text-yellow-300">
                    ⚠️ Sistem yeniden başlatma gerekiyor
                  </div>
                )}
                {sel.packages_to_update.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold text-slate-300 mb-2">Güncellenecek ({sel.packages_to_update.length})</div>
                    <div className="bg-slate-900 rounded-xl p-3 max-h-40 overflow-y-auto space-y-0.5">
                      {sel.packages_to_update.slice(0,30).map((p,i) => (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          {p.is_security && <span className="text-red-400">🔒</span>}
                          {p.is_kernel   && <span className="text-purple-400">⚡</span>}
                          <span className="text-slate-200 font-mono">{p.name}</span>
                          {p.new_version && <span className="text-slate-400">→ {p.new_version}</span>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {sel.packages_updated.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold text-green-300 mb-2">✓ Güncellendi ({sel.packages_updated.length})</div>
                    <div className="bg-slate-900 rounded-xl p-3 max-h-32 overflow-y-auto space-y-0.5">
                      {sel.packages_updated.slice(0,20).map((p,i) => (
                        <div key={i} className="text-xs text-green-300 font-mono">{p.name} {p.version}</div>
                      ))}
                    </div>
                  </div>
                )}
                {sel.log && (
                  <div>
                    <div className="text-xs font-semibold text-slate-300 mb-2">Çıktı</div>
                    <pre className="bg-slate-900 border border-slate-700 rounded-xl p-4 text-xs text-green-300 font-mono whitespace-pre-wrap max-h-64 overflow-y-auto">{sel.log}</pre>
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

// ─── Main Page ────────────────────────────────────────────────────────────────
const SystemUpdate: React.FC = () => {
  const [step, setStep] = useState(1)
  const [showWizard, setShowWizard] = useState(false)

  // Wizard state
  const [selectedDistro,  setSelectedDistro]  = useState('')        // adım 1
  const [servers,         setServers]          = useState<ServerItem[]>([])
  const [selectedServers, setSelectedServers]  = useState<number[]>([])
  // Adım 3 — Yetkili kullanıcı
  const [credMode,     setCredMode]     = useState<'stored'|'override'>('stored')
  const [overrideUser, setOverrideUser] = useState('')
  const [overridePass, setOverridePass] = useState('')
  const [overrideSudo, setOverrideSudo] = useState('')
  const [privMethod,   setPrivMethod]   = useState<'sudo'|'dzdo'|'su'|'pbrun'|'direct'>('sudo')
  // Adım 4 — Repo
  const [repos,           setRepos]            = useState<RepoSource[]>([])
  const [filteredRepos,   setFilteredRepos]    = useState<RepoSource[]>([])
  const [selectedRepo,    setSelectedRepo]     = useState<number|null>(null)
  // Adım 5 — Mod
  const [updateType,      setUpdateType]       = useState('')
  const [planName,        setPlanName]         = useState('')
  const [analyzing,       setAnalyzing]        = useState(false)
  const [aiAnalysis,      setAiAnalysis]       = useState('')
  const [currentPlan,     setCurrentPlan]      = useState<UpdatePlan|null>(null)
  const [planJobs,        setPlanJobs]         = useState<UpdateJob[]>([])

  // History
  const [plans,    setPlans]    = useState<UpdatePlan[]>([])
  const [viewPlan, setViewPlan] = useState<UpdatePlan|null>(null)
  const [toast,    setToast]    = useState<{msg:string; type:'ok'|'err'}|null>(null)

  const showToast = (msg: string, type: 'ok'|'err' = 'ok') => {
    setToast({msg, type}); setTimeout(() => setToast(null), 5000)
  }

  const loadPlans = useCallback(async () => {
    const r = await fetch(`${API}/plans`)
    if (r.ok) setPlans(await r.json())
  }, [])

  // Load all repos once
  useEffect(() => {
    loadPlans()
    fetch('/api/v1/repos').then(r => r.json()).then(setRepos).catch(() => {})
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
    fetch(url).then(r => r.json()).then(setServers).catch(() => {})

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

  // Auto-refresh current plan jobs
  useEffect(() => {
    if (!currentPlan || currentPlan.status !== 'running') return
    const t = setInterval(async () => {
      const [pr, jr] = await Promise.all([
        fetch(`${API}/plans/${currentPlan.id}`),
        fetch(`${API}/plans/${currentPlan.id}/jobs`),
      ])
      if (pr.ok) setCurrentPlan(await pr.json())
      if (jr.ok) setPlanJobs(await jr.json())
    }, 4000)
    return () => clearInterval(t)
  }, [currentPlan])

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
    const r = await fetch(`${API}/plans`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (r.ok) { setCurrentPlan(await r.json()); setStep(6) }
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
        setStep(7)
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
      setStep(8)
      showToast('Güncelleme başlatıldı')
      await loadPlans()
    }
  }

  const handleDeletePlan = async (id: number) => {
    if (!confirm('Plan silinsin mi?')) return
    const r = await fetch(`${API}/plans/${id}`, { method: 'DELETE' })
    if (r.ok) { showToast('Silindi'); await loadPlans() }
    else showToast('Hata', 'err')
  }

  const resetWizard = () => {
    setStep(1); setSelectedDistro(''); setSelectedServers([]); setSelectedRepo(null)
    setUpdateType(''); setPlanName(''); setAiAnalysis('')
    setCredMode('stored'); setOverrideUser(''); setOverridePass(''); setOverrideSudo(''); setPrivMethod('sudo')
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
          <button onClick={() => setShowWizard(true)}
            className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl transition-colors">
            + Yeni Güncelleme
          </button>
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-xl border shadow-lg text-sm font-medium ${
          toast.type==='ok' ? 'bg-green-900/90 border-green-500/50 text-green-300' : 'bg-red-900/90 border-red-500/50 text-red-300'
        }`}>{toast.type==='ok'?'✓ ':'✗ '}{toast.msg}</div>
      )}

      {/* ── WIZARD ────────────────────────────────────────────────────────── */}
      {showWizard && (
        <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6">
          <Steps current={step} />

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
                        isSelected ? d.color + ' border-2' : 'border-slate-600 bg-slate-700/20 hover:border-slate-500 hover:bg-slate-700/40'
                      }`}>
                      <div className="text-4xl mb-3">{d.icon}</div>
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
                <span className="text-3xl">{DISTRO_LIST.find(d=>d.key===selectedDistro)?.icon}</span>
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
                    <span className="font-medium">⚠️ {servers.filter(s => !s.has_os_info).length} sunucuda OS bilgisi yok</span>
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
                <button onClick={() => setStep(1)} className="px-5 py-2.5 text-sm text-slate-400 hover:text-white transition-colors">← Geri</button>
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
                  credMode === 'stored' ? 'border-green-500 bg-green-500/10' : 'border-slate-600 bg-slate-700/20 hover:border-slate-500'
                }`}>
                  <input type="radio" checked={credMode==='stored'} onChange={() => setCredMode('stored')}
                    className="accent-green-500 w-4 h-4 mt-0.5 flex-shrink-0" />
                  <div>
                    <div className="text-sm font-semibold text-white flex items-center gap-2">
                      🔑 Sunucu Kayıtlı Kimlik Bilgilerini Kullan
                    </div>
                    <div className="text-xs text-slate-400 mt-1">
                      Her sunucu için kendi connection_config veya global credentials kullanılır.
                      <br/>Sunucularda sudo/root erişimi tanımlı olmalı.
                    </div>
                  </div>
                </label>

                {/* Seçenek 2: Özel kullanıcı */}
                <label className={`flex items-start gap-4 p-4 rounded-xl border-2 cursor-pointer transition-all ${
                  credMode === 'override' ? 'border-blue-500 bg-blue-500/10' : 'border-slate-600 bg-slate-700/20 hover:border-slate-500'
                }`}>
                  <input type="radio" checked={credMode==='override'} onChange={() => setCredMode('override')}
                    className="accent-blue-500 w-4 h-4 mt-0.5 flex-shrink-0" />
                  <div className="flex-1">
                    <div className="text-sm font-semibold text-white flex items-center gap-2">
                      👤 Özel Yetkili Kullanıcı Belirt
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
                            className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">SSH Şifresi</label>
                            <input type="password" value={overridePass} onChange={e => setOverridePass(e.target.value)}
                              placeholder="SSH şifresi"
                              className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                          </div>
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">
                              Sudo Şifresi
                              <span className="text-slate-500 ml-1">(root ise boş bırakın)</span>
                            </label>
                            <input type="password" value={overrideSudo} onChange={e => setOverrideSudo(e.target.value)}
                              placeholder="sudo şifresi (boşsa SSH şifresi kullanılır)"
                              className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                          </div>
                        </div>
                        <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg px-3 py-2 text-xs text-blue-300">
                          💡 Root kullanıcı ise sudo şifresi boş bırakın.
                          Sudo kullanıcı ise SSH şifresi = sudo şifresi olabilir.
                        </div>
                      </div>
                    )}
                  </div>
                </label>
              </div>

              {/* Yetki Yükseltme Yöntemi */}
              <div className="bg-slate-700/30 border border-slate-600 rounded-xl p-4 space-y-3">
                <div>
                  <div className="text-sm font-semibold text-white">Yetki Yükseltme Yöntemi</div>
                  <div className="text-xs text-slate-400 mt-0.5">Komutları hangi yöntemle root yetkisiyle çalıştıracak?</div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {([
                    { key: 'sudo',   label: 'sudo',   desc: 'Standart Linux',         icon: '🔑' },
                    { key: 'dzdo',   label: 'dzdo',   desc: 'Centrify DirectControl',  icon: '🏢' },
                    { key: 'su',     label: 'su',     desc: 'Switch User',             icon: '👤' },
                    { key: 'pbrun',  label: 'pbrun',  desc: 'BeyondTrust / Powerbroker',icon: '🛡️'},
                    { key: 'direct', label: 'Direct', desc: 'Root kullanıcı (şifresiz)',icon: '⚡' },
                  ] as const).map(m => (
                    <button key={m.key} onClick={() => setPrivMethod(m.key)}
                      className={`p-3 rounded-xl border text-left transition-all ${
                        privMethod === m.key
                          ? 'border-blue-500 bg-blue-600/15'
                          : 'border-slate-600 bg-slate-700/20 hover:border-slate-500'
                      }`}>
                      <div className="flex items-center gap-2">
                        <span className="text-base">{m.icon}</span>
                        <span className={`text-sm font-bold ${privMethod === m.key ? 'text-white' : 'text-slate-300'}`}>
                          {m.label}
                        </span>
                      </div>
                      <div className="text-xs text-slate-500 mt-0.5">{m.desc}</div>
                    </button>
                  ))}
                </div>
                {privMethod === 'dzdo' && (
                  <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg px-3 py-2 text-xs text-blue-300">
                    💡 <strong>dzdo</strong> (Centrify DirectControl): AD hesabınız dzdo ile yetkili ise AD şifrenizi SSH şifresi olarak girin.
                    Şifresiz çalışıyorsa "Direct" seçin.
                  </div>
                )}
                {privMethod === 'direct' && (
                  <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg px-3 py-2 text-xs text-yellow-300">
                    ⚠️ <strong>Direct</strong>: root kullanıcı olarak direkt bağlanılır, ekstra yetki yükseltme yapılmaz.
                  </div>
                )}
              </div>

              {/* Özet */}
              <div className="bg-slate-700/30 border border-slate-600 rounded-xl p-4">
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
                <button onClick={() => setStep(2)} className="px-5 py-2.5 text-sm text-slate-400 hover:text-white transition-colors">← Geri</button>
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
                  selectedRepo === null ? 'border-blue-500 bg-blue-600/10' : 'border-slate-600 hover:border-slate-500 bg-slate-700/20'
                }`}>
                  <input type="radio" checked={selectedRepo===null} onChange={() => setSelectedRepo(null)} className="accent-blue-500 w-4 h-4 flex-shrink-0" />
                  <div>
                    <div className="text-sm font-semibold text-white">🌐 Varsayılan Repo</div>
                    <div className="text-xs text-slate-400 mt-0.5">Sunucunun /etc/yum.repos.d/ veya apt sources.list kaynakları</div>
                  </div>
                </label>

                {/* Local repolar */}
                {filteredRepos.length > 0 ? (
                  filteredRepos.map(repo => (
                    <label key={repo.id} className={`flex items-center gap-4 p-4 rounded-xl border-2 cursor-pointer transition-all ${
                      selectedRepo===repo.id ? 'border-blue-500 bg-blue-600/10' : 'border-slate-600 hover:border-slate-500 bg-slate-700/20'
                    }`}>
                      <input type="radio" checked={selectedRepo===repo.id} onChange={() => setSelectedRepo(repo.id)} className="accent-blue-500 w-4 h-4 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-semibold text-white">{repo.display_name}</div>
                        <div className="text-xs text-slate-400 mt-0.5">
                          {repo.repo_type.toUpperCase()} · Local mirror ·
                          <span className={`ml-1 ${repo.sync_status === 'synced' ? 'text-green-400' : 'text-yellow-400'}`}>
                            {repo.sync_status === 'synced' ? '✓ Güncel' : '⚠ Kısmi'}
                          </span>
                        </div>
                      </div>
                    </label>
                  ))
                ) : (
                  <div className="bg-slate-700/30 border border-slate-600 rounded-xl p-4 text-center text-xs text-slate-400">
                    {selectedDistro
                      ? `${DISTRO_LIST.find(d=>d.key===selectedDistro)?.short} için senkronize local repo bulunamadı`
                      : 'Senkronize local repo yok'} — Varsayılan repo kullanılacak
                  </div>
                )}
              </div>

              <div className="flex justify-between">
                <button onClick={() => setStep(3)} className="px-5 py-2.5 text-sm text-slate-400 hover:text-white transition-colors">← Geri</button>
                <button onClick={() => setStep(5)}
                  className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl transition-colors">
                  Güncelleme Modu →
                </button>
              </div>
            </div>
          )}

          {/* ── Adım 5: Güncelleme Modu ───────────────────────────────────── */}
          {step === 5 && (
            <div className="space-y-5">
              <div>
                <h2 className="text-base font-semibold text-white">Güncelleme Modu</h2>
                <p className="text-xs text-slate-400 mt-0.5">Ne tür güncelleme yapılacak?</p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {UPDATE_TYPES.map(t => (
                  <button key={t.key} onClick={() => setUpdateType(t.key)}
                    className={`p-5 rounded-xl border-2 text-left transition-all ${
                      updateType === t.key ? t.color + ' border-2' : 'border-slate-600 bg-slate-700/20 hover:border-slate-500 hover:bg-slate-700/40'
                    }`}>
                    <div className="text-4xl mb-3">{t.icon}</div>
                    <div className="text-base font-bold text-white">{t.label}</div>
                    <div className="text-xs text-slate-400 mt-1">{t.desc}</div>
                  </button>
                ))}
              </div>

              {/* Özet + Plan adı */}
              {updateType && (
                <div className="bg-slate-700/40 border border-slate-600 rounded-xl p-4 space-y-3">
                  <div className="text-xs font-semibold text-slate-300 mb-2">Plan Özeti</div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                    <div className="bg-slate-700/50 rounded-lg p-2 text-center">
                      <div className="text-xl">{DISTRO_LIST.find(d=>d.key===selectedDistro)?.icon}</div>
                      <div className="text-slate-400 mt-0.5">{DISTRO_LIST.find(d=>d.key===selectedDistro)?.short}</div>
                    </div>
                    <div className="bg-slate-700/50 rounded-lg p-2 text-center">
                      <div className="text-lg font-bold text-white">{selectedServers.length}</div>
                      <div className="text-slate-400">Sunucu</div>
                    </div>
                    <div className="bg-slate-700/50 rounded-lg p-2 text-center">
                      <div className="text-lg">{UPDATE_TYPES.find(t=>t.key===updateType)?.icon}</div>
                      <div className="text-slate-400 mt-0.5">{UPDATE_TYPES.find(t=>t.key===updateType)?.label}</div>
                    </div>
                    <div className="bg-slate-700/50 rounded-lg p-2 text-center">
                      <div className="text-xs text-white font-medium">{selectedRepo ? '📦 Local' : '🌐 Varsayılan'}</div>
                      <div className="text-slate-400">Repo</div>
                    </div>
                  </div>
                  <div>
                    <label className="text-xs text-slate-400 block mb-1">Plan Adı (isteğe bağlı)</label>
                    <input value={planName} onChange={e => setPlanName(e.target.value)}
                      placeholder={`${DISTRO_LIST.find(d=>d.key===selectedDistro)?.short || 'Linux'} ${UPDATE_TYPES.find(t=>t.key===updateType)?.label} — ${new Date().toLocaleDateString('tr-TR')}`}
                      className="w-full bg-slate-700 text-white text-sm px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500" />
                  </div>
                </div>
              )}

              {updateType === 'kernel' && (
                <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl px-4 py-3 text-sm text-yellow-300">
                  ⚠️ Kernel güncellemesi sonrası sunucular yeniden başlatılmalıdır.
                </div>
              )}

              <div className="flex justify-between">
                <button onClick={() => setStep(4)} className="px-5 py-2.5 text-sm text-slate-400 hover:text-white transition-colors">← Geri</button>
                <button onClick={handleCreatePlan} disabled={!updateType}
                  className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl disabled:opacity-40 transition-colors">
                  AI Analiz →
                </button>
              </div>
            </div>
          )}

          {/* ── Adım 6: AI Analiz ─────────────────────────────────────────── */}
          {step === 6 && (
            <div className="space-y-4">
              <h2 className="text-base font-semibold text-white">🤖 AI Ön Analiz</h2>
              {!aiAnalysis && !analyzing && (
                <div className="bg-slate-700/30 border border-slate-600 rounded-xl p-8 text-center space-y-4">
                  <div className="text-5xl">🤖</div>
                  <div className="text-sm text-slate-300">AI sunucuları kontrol edecek ve güncelleme planını analiz edecek</div>
                  <div className="text-xs text-slate-500">Güncelleme riskleri, reboot gereklilikleri ve önerilen sıra belirlenecek</div>
                  <button onClick={handleAnalyze}
                    className="px-6 py-3 bg-cyan-700 hover:bg-cyan-600 text-white font-semibold rounded-xl transition-colors">
                    AI Analizini Başlat
                  </button>
                </div>
              )}
              {analyzing && (
                <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-8 text-center space-y-4">
                  <div className="w-12 h-12 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
                  <div className="text-sm text-blue-300 animate-pulse">
                    Sunucular SSH ile kontrol ediliyor, AI analiz yapıyor...
                  </div>
                </div>
              )}
              {aiAnalysis && (
                <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-xl p-5">
                  <div className="text-xs font-semibold text-cyan-400 mb-3 flex items-center gap-2">
                    <span>🤖</span> AI Analiz Sonucu
                  </div>
                  <div className="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">{aiAnalysis}</div>
                </div>
              )}
              <div className="flex justify-between">
                <button onClick={() => setStep(5)} className="px-5 py-2.5 text-sm text-slate-400 hover:text-white transition-colors">← Geri</button>
                {aiAnalysis && (
                  <button onClick={() => setStep(7)}
                    className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl transition-colors">
                    İncele & Onayla →
                  </button>
                )}
              </div>
            </div>
          )}

          {/* ── Adım 7: Onay ──────────────────────────────────────────────── */}
          {step === 7 && currentPlan && (
            <div className="space-y-5">
              <h2 className="text-base font-semibold text-white">Güncellemeyi Onayla</h2>

              <div className="bg-slate-700/50 rounded-xl p-5">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                  <div className="text-center">
                    <div className="text-3xl mb-1">{DISTRO_LIST.find(d=>d.key===selectedDistro)?.icon}</div>
                    <div className="text-slate-400 text-xs">{DISTRO_LIST.find(d=>d.key===selectedDistro)?.label}</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-white">{selectedServers.length}</div>
                    <div className="text-slate-400 text-xs">Sunucu</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl">{UPDATE_TYPES.find(t=>t.key===updateType)?.icon}</div>
                    <div className="text-slate-400 text-xs">{UPDATE_TYPES.find(t=>t.key===updateType)?.label}</div>
                  </div>
                  <div className="text-center">
                    <div className="text-sm font-medium text-white">{selectedRepo ? '📦 Local' : '🌐 Varsayılan'}</div>
                    <div className="text-slate-400 text-xs">Repo</div>
                  </div>
                  <div className="text-center">
                    <div className="text-sm font-medium text-white">
                      {credMode === 'override' && overrideUser ? `👤 ${overrideUser}` : '🔑 Kayıtlı'}
                    </div>
                    <div className="text-slate-400 text-xs">Kullanıcı</div>
                  </div>
                  <div className="text-center">
                    <div className="text-sm font-medium text-white">
                      {privMethod === 'sudo'  ? '🔑 sudo' :
                       privMethod === 'dzdo'  ? '🏢 dzdo' :
                       privMethod === 'su'    ? '👤 su'   :
                       privMethod === 'pbrun' ? '🛡️ pbrun' : '⚡ direct'}
                    </div>
                    <div className="text-slate-400 text-xs">Yetki</div>
                  </div>
                </div>
              </div>

              {updateType === 'kernel' && (
                <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl px-4 py-3 text-sm text-yellow-300">
                  ⚠️ Kernel güncellemesi sonrası reboot gerekecek — bunu önceden planlayın.
                </div>
              )}

              {aiAnalysis && (
                <details className="bg-slate-700/30 border border-slate-600 rounded-xl">
                  <summary className="px-4 py-3 text-sm text-cyan-400 cursor-pointer select-none">
                    🤖 AI Analiz Özetini Göster
                  </summary>
                  <div className="px-4 pb-4 text-xs text-slate-300 leading-relaxed whitespace-pre-wrap border-t border-slate-600 pt-3 mt-0">
                    {aiAnalysis}
                  </div>
                </details>
              )}

              <div className="flex justify-between">
                <button onClick={() => setStep(6)} className="px-5 py-2.5 text-sm text-slate-400 hover:text-white transition-colors">← Geri</button>
                <button onClick={handleRun}
                  className="px-8 py-3 bg-green-700 hover:bg-green-600 text-white font-bold text-sm rounded-xl transition-colors flex items-center gap-2">
                  ✓ Onayla ve Güncellemeyi Başlat
                </button>
              </div>
            </div>
          )}

          {/* ── Adım 8: Canlı İzleme ──────────────────────────────────────── */}
          {step === 8 && currentPlan && (
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
                <div className="bg-slate-700 rounded-full h-2.5">
                  <div className="bg-blue-500 h-2.5 rounded-full transition-all duration-500"
                    style={{ width: `${Math.round(currentPlan.completed_servers*100/Math.max(currentPlan.total_servers,1))}%` }} />
                </div>
              </div>

              <div className="space-y-2">
                {planJobs.map(j => (
                  <div key={j.id} className="flex items-center gap-3 bg-slate-700/40 rounded-xl px-4 py-3">
                    <span className={`text-xs font-medium w-24 flex-shrink-0 ${STATUS_COLOR[j.status]}`}>
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
                    {j.packages_updated.length > 0 && (
                      <span className="text-xs text-green-400 flex-shrink-0">{j.packages_updated.length} paket</span>
                    )}
                    {j.reboot_required && <span className="text-xs text-yellow-400 flex-shrink-0">⚠️ Reboot</span>}
                  </div>
                ))}
              </div>

              {currentPlan.ai_summary && (
                <div className="bg-green-500/5 border border-green-500/20 rounded-xl p-4">
                  <div className="text-xs font-semibold text-green-400 mb-2">✅ AI Güncelleme Özeti</div>
                  <div className="text-sm text-slate-200 leading-relaxed">{currentPlan.ai_summary}</div>
                </div>
              )}

              {['completed','failed','partial'].includes(currentPlan.status) && (
                <button onClick={resetWizard}
                  className="w-full py-3 bg-slate-700 hover:bg-slate-600 text-white text-sm font-medium rounded-xl transition-colors">
                  ← Plan Listesine Dön
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── GEÇMİŞ ──────────────────────────────────────────────────────── */}
      {!showWizard && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white">Güncelleme Geçmişi</h2>
            <button onClick={loadPlans} className="text-xs text-slate-400 hover:text-white px-2 py-1 hover:bg-slate-700 rounded transition-colors">↻ Yenile</button>
          </div>
          {plans.length === 0 ? (
            <div className="py-16 text-center space-y-3">
              <div className="text-5xl">🔄</div>
              <div className="text-slate-400 text-sm">Henüz güncelleme yapılmadı</div>
              <button onClick={() => setShowWizard(true)}
                className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold rounded-xl transition-colors">
                İlk Güncellemeyi Başlat
              </button>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-700/50 border-b border-slate-600">
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-300 uppercase tracking-wide">Plan</th>
                  <th className="text-left px-3 py-2.5 text-xs font-semibold text-slate-300 uppercase tracking-wide">Mod</th>
                  <th className="text-left px-3 py-2.5 text-xs font-semibold text-slate-300 uppercase tracking-wide">Durum</th>
                  <th className="text-center px-3 py-2.5 text-xs font-semibold text-slate-300 uppercase tracking-wide">İlerleme</th>
                  <th className="text-left px-3 py-2.5 text-xs font-semibold text-slate-300 uppercase tracking-wide">İşlem</th>
                </tr>
              </thead>
              <tbody>
                {plans.map(p => (
                  <PlanRow key={p.id} plan={p} onView={setViewPlan} onDelete={handleDeletePlan} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {viewPlan && <PlanDetailModal plan={viewPlan} onClose={() => setViewPlan(null)} />}
    </div>
  )
}

export default SystemUpdate
