import React, { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

interface Server {
  id: number
  name: string
  hostname?: string
  ip_address: string
  status: string
  ai_ready: boolean
  os_type?: string
}

// Windows sunucular bu sayfada gösterilmez — SSH/Ansible yerine WinRM kullanırlar.
// Bkz. /windows/ansible (Windows modülündeki Ansible/AWX sayfası).
const isWindowsServer = (s: Server) => (s.os_type || '').toLowerCase().includes('windows')

interface AWXTemplate {
  id: number
  name: string
  description: string
}

// ── Design tokens (matches NEON palette used across the app) ──────────────
const NEON = {
  blue:   '#3b82f6',
  cyan:   '#22d3ee',
  green:  '#10b981',
  orange: '#f59e0b',
  red:    '#f87171',
  slate:  '#64748b',
}

function rgb(hex: string) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `${r},${g},${b}`
}

// ── Shared primitives ─────────────────────────────────────────────────────
const card = 'bg-[#0d1422] border border-white/[0.07] rounded-[10px]'
const inputCls = 'w-full bg-[#080d16] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-[#e8edf5] placeholder-slate-600 focus:outline-none focus:border-blue-500/60'

type Tab = 'command' | 'playbook' | 'awx'

const TAB_LABELS: Record<Tab, string> = {
  command:  'Ad-Hoc Komut',
  playbook: 'YAML Playbook',
  awx:      'AWX Job Template',
}

const MODULES = ['shell', 'command', 'yum', 'apt', 'service', 'copy', 'file', 'ping']

const STATUS_COLOR: Record<string, string> = {
  successful: '#10b981',
  failed:     '#f87171',
  running:    '#3b82f6',
  pending:    '#f59e0b',
  canceled:   '#64748b',
}

// ── Main component ────────────────────────────────────────────────────────
const Ansible: React.FC = () => {
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [search, setSearch]           = useState('')
  const [tab, setTab]                 = useState<Tab>('command')

  // Command tab
  const [module, setModule]     = useState('shell')
  const [args, setArgs]         = useState('')
  const [become, setBecome]     = useState(false)

  // Playbook tab
  const [yaml, setYaml] = useState('')

  // AWX tab
  const [templateId, setTemplateId] = useState<number | null>(null)
  const [extraVars, setExtraVars]   = useState('')
  const [jobId, setJobId]           = useState<number | null>(null)

  // Results
  const [result, setResult] = useState<any>(null)

  // ── Data fetching ────────────────────────────────────────────────────────
  const { data: allServers = [] } = useQuery<Server[]>({
    queryKey: ['servers'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/servers/`)
      if (!res.ok) throw new Error('Sunucular alınamadı')
      return res.json()
    },
  })

  const sshServers = allServers.filter(
    s => s.ai_ready && s.status === 'ONLINE' && s.ip_address?.trim() && !isWindowsServer(s)
  )

  const filtered = search
    ? sshServers.filter(s => {
        const q = search.toLowerCase()
        return (
          s.name.toLowerCase().includes(q) ||
          s.ip_address?.toLowerCase().includes(q) ||
          s.hostname?.toLowerCase().includes(q)
        )
      })
    : sshServers

  const { data: templates = [] } = useQuery<AWXTemplate[]>({
    queryKey: ['awx-templates'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/ansible/awx/templates`)
      if (!res.ok) return []
      const data = await res.json()
      return data.templates || []
    },
    retry: false,
  })

  const { data: jobStatus } = useQuery({
    queryKey: ['awx-job', jobId],
    queryFn: async () => {
      if (!jobId) return null
      const res = await fetch(`${API_BASE_URL}/ansible/awx/job/${jobId}`)
      const data = await res.json()
      return data.job
    },
    enabled: !!jobId,
    refetchInterval: q => {
      const s = q.state.data?.status
      return s === 'pending' || s === 'running' ? 3000 : false
    },
  })

  // ── Mutations ────────────────────────────────────────────────────────────
  const runAdHoc = useMutation({
    mutationFn: async () => {
      if (tab === 'playbook') {
        const res = await fetch(`${API_BASE_URL}/ansible/playbook`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ server_ids: selectedIds, playbook_content: yaml }),
        })
        if (!res.ok) throw new Error('Playbook çalıştırılamadı')
        return res.json()
      }
      const res = await fetch(`${API_BASE_URL}/ansible/adhoc`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ server_ids: selectedIds, module, args, become }),
      })
      if (!res.ok) throw new Error('Ad-hoc komut başarısız')
      return res.json()
    },
    onSuccess: data => setResult(data),
    onError: (err: Error) => alert(`Hata: ${err.message}`),
  })

  const launchAWX = useMutation({
    mutationFn: async () => {
      const extra = extraVars ? JSON.parse(extraVars) : undefined
      const res = await fetch(`${API_BASE_URL}/ansible/awx/launch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          template_id: templateId,
          server_ids: selectedIds.length > 0 ? selectedIds : undefined,
          extra_vars: extra,
        }),
      })
      if (!res.ok) throw new Error('AWX job başlatılamadı')
      return res.json()
    },
    onSuccess: data => {
      setJobId(data.job_id)
    },
  })

  // ── Helpers ──────────────────────────────────────────────────────────────
  const toggle = (id: number) =>
    setSelectedIds(prev => (prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]))

  const successCount = result?.results
    ? Object.values(result.results).filter((r: any) => r.rc === 0).length
    : 0
  const failCount = result?.failed?.length ?? 0

  const canRun =
    selectedIds.length > 0 &&
    (tab === 'command' ? !!args : tab === 'playbook' ? !!yaml.trim() : false) &&
    !runAdHoc.isPending

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-6 min-h-0">

      {/* Page header */}
      <div>
        <h1 className="text-xl font-semibold text-[#e8edf5]">Ansible & AWX</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Toplu komut çalıştırma ve playbook yönetimi (yalnızca Linux/SSH sunucular — Windows sunucular için
          Windows modülündeki Ansible/AWX sayfasını kullanın)
        </p>
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 xl:grid-cols-[320px_1fr] gap-5">

        {/* ── Left: Server selection ─────────────────────────────────────── */}
        <div className={`${card} flex flex-col min-h-0`}>
          <div className="px-5 py-4 border-b border-white/[0.06] flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">Sunucular</p>
              <p className="text-sm font-semibold text-[#e8edf5] mt-0.5">
                {selectedIds.length > 0
                  ? <span style={{ color: NEON.blue }}>{selectedIds.length} seçili</span>
                  : <span className="text-slate-500">Seçilmedi</span>
                }
                <span className="text-slate-600 font-normal"> / {sshServers.length} hazır</span>
              </p>
            </div>
            <div className="flex gap-1.5">
              <button onClick={() => setSelectedIds(filtered.map(s => s.id))}
                className="px-2.5 py-1 text-xs rounded-lg text-blue-400 border border-blue-500/30 bg-blue-500/10 hover:bg-blue-500/20 transition-colors">
                Tümü
              </button>
              <button onClick={() => setSelectedIds([])}
                className="px-2.5 py-1 text-xs rounded-lg text-slate-400 border border-white/[0.06] hover:bg-white/[0.04] transition-colors">
                Temizle
              </button>
            </div>
          </div>

          {/* Search */}
          <div className="px-4 pt-3 pb-2">
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Sunucu ara (isim, IP)..."
              className={inputCls}
            />
          </div>

          {/* Server list */}
          <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-0.5 max-h-[320px] xl:max-h-none">
            {filtered.length === 0 ? (
              <div className="py-8 text-center text-slate-600 text-sm">
                {search ? `"${search}" araması için sonuç yok` : 'SSH yapılabilen sunucu yok'}
              </div>
            ) : filtered.map(s => {
              const sel = selectedIds.includes(s.id)
              return (
                <label key={s.id}
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-colors ${
                    sel
                      ? 'bg-blue-600/10 border border-blue-500/20'
                      : 'hover:bg-white/[0.03] border border-transparent'
                  }`}>
                  <input type="checkbox" checked={sel} onChange={() => toggle(s.id)}
                    className="w-3.5 h-3.5 accent-blue-500 flex-shrink-0" />
                  <div className="min-w-0">
                    <p className="text-sm text-[#e8edf5] truncate">{s.name}</p>
                    <p className="text-[11px] font-mono text-slate-500">{s.ip_address}</p>
                  </div>
                  <span className="ml-auto flex-shrink-0 w-1.5 h-1.5 rounded-full"
                    style={{ background: NEON.green }} />
                </label>
              )
            })}
          </div>
        </div>

        {/* ── Right: Execution panel ─────────────────────────────────────── */}
        <div className="flex flex-col gap-4 min-w-0">

          {/* Tab bar */}
          <div className={`${card} p-1 flex gap-1`}>
            {(Object.keys(TAB_LABELS) as Tab[]).map(t => (
              <button key={t} onClick={() => setTab(t)}
                className={`flex-1 px-4 py-2 rounded-[8px] text-sm font-medium transition-all ${
                  tab === t
                    ? 'bg-blue-600 text-white'
                    : 'text-slate-400 hover:text-[#e8edf5] hover:bg-white/[0.03]'
                }`}>
                {TAB_LABELS[t]}
              </button>
            ))}
          </div>

          {/* ── Tab: Ad-Hoc Command ──────────────────────────────────────── */}
          {tab === 'command' && (
            <div className={`${card} p-5 space-y-4`}>
              <div className="grid grid-cols-1 md:grid-cols-[160px_1fr] gap-4">
                <div>
                  <label className="block text-xs text-slate-500 mb-1.5 font-medium uppercase tracking-wider">Modül</label>
                  <select value={module} onChange={e => setModule(e.target.value)} className={inputCls}>
                    {MODULES.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-slate-500 mb-1.5 font-medium uppercase tracking-wider">Argümanlar</label>
                  <input
                    type="text"
                    value={args}
                    onChange={e => setArgs(e.target.value)}
                    placeholder='örn: "uptime" veya "name=vim state=present"'
                    className={`${inputCls} font-mono`}
                  />
                </div>
              </div>

              <label className="flex items-center gap-2.5 text-sm text-slate-400 cursor-pointer select-none w-fit">
                <input type="checkbox" checked={become} onChange={e => setBecome(e.target.checked)}
                  className="w-3.5 h-3.5 accent-blue-500" />
                Sudo ile çalıştır (become)
              </label>

              <div className="flex items-center gap-3 pt-1">
                <button
                  onClick={() => runAdHoc.mutate()}
                  disabled={!canRun}
                  className="px-5 py-2 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-2">
                  {runAdHoc.isPending && (
                    <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  )}
                  {runAdHoc.isPending ? 'Çalıştırılıyor...' : 'Komutu Çalıştır'}
                </button>
                {selectedIds.length === 0 && (
                  <span className="text-xs text-slate-600">Soldan sunucu seçin</span>
                )}
              </div>
            </div>
          )}

          {/* ── Tab: Playbook ────────────────────────────────────────────── */}
          {tab === 'playbook' && (
            <div className={`${card} p-5 space-y-4`}>
              <div>
                <label className="block text-xs text-slate-500 mb-1.5 font-medium uppercase tracking-wider">
                  Ansible Playbook (YAML)
                </label>
                <textarea
                  value={yaml}
                  onChange={e => setYaml(e.target.value)}
                  rows={12}
                  className={`${inputCls} font-mono text-xs leading-relaxed resize-y`}
                  placeholder={`---\n- name: Örnek Playbook\n  hosts: all\n  become: yes\n  tasks:\n    - name: Paket yükle\n      yum:\n        name: vim\n        state: present`}
                />
                <p className="text-[11px] text-slate-600 mt-1.5">
                  "hosts: all" → seçili sunuculara uygulanır
                </p>
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={() => runAdHoc.mutate()}
                  disabled={selectedIds.length === 0 || !yaml.trim() || runAdHoc.isPending}
                  className="px-5 py-2 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-2">
                  {runAdHoc.isPending && (
                    <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  )}
                  {runAdHoc.isPending ? 'Çalıştırılıyor...' : 'Playbook Çalıştır'}
                </button>
                {selectedIds.length === 0 && (
                  <span className="text-xs text-slate-600">Soldan sunucu seçin</span>
                )}
              </div>
            </div>
          )}

          {/* ── Tab: AWX ────────────────────────────────────────────────── */}
          {tab === 'awx' && (
            <div className={`${card} p-5 space-y-4`}>
              {templates.length === 0 ? (
                <div className="py-6 text-center">
                  <p className="text-sm text-slate-500 mb-1">AWX yapılandırılmamış veya job template yok</p>
                  <p className="text-xs text-slate-600 font-mono">AWX_URL · AWX_USERNAME · AWX_PASSWORD</p>
                </div>
              ) : (
                <>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1.5 font-medium uppercase tracking-wider">
                      Job Template
                    </label>
                    <select
                      value={templateId || ''}
                      onChange={e => setTemplateId(Number(e.target.value))}
                      className={inputCls}>
                      <option value="">— Seçin —</option>
                      {templates.map(t => (
                        <option key={t.id} value={t.id}>
                          {t.name}{t.description ? ` — ${t.description}` : ''}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs text-slate-500 mb-1.5 font-medium uppercase tracking-wider">
                      Extra Vars <span className="normal-case font-normal">(JSON, opsiyonel)</span>
                    </label>
                    <textarea
                      value={extraVars}
                      onChange={e => setExtraVars(e.target.value)}
                      placeholder='{"key": "value"}'
                      rows={3}
                      className={`${inputCls} font-mono text-xs`}
                    />
                  </div>

                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => launchAWX.mutate()}
                      disabled={!templateId || launchAWX.isPending}
                      className="px-5 py-2 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-2">
                      {launchAWX.isPending && (
                        <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      )}
                      {launchAWX.isPending ? 'Başlatılıyor...' : 'Job Başlat'}
                    </button>
                  </div>
                </>
              )}

              {/* AWX Job status */}
              {jobId && jobStatus && (
                <div className="border-t border-white/[0.06] pt-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">
                      Job #{jobId}
                    </p>
                    <button onClick={() => setJobId(null)}
                      className="text-xs text-slate-600 hover:text-slate-400">Kapat</button>
                  </div>

                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { label: 'Durum', value: jobStatus.status?.toUpperCase() },
                      { label: 'İsim', value: jobStatus.name },
                      { label: 'Süre', value: jobStatus.elapsed ? `${jobStatus.elapsed}s` : '—' },
                    ].map(row => (
                      <div key={row.label} className="bg-[#080d16] rounded-lg p-3">
                        <p className="text-[10px] text-slate-600 uppercase tracking-wider mb-1">{row.label}</p>
                        <p className="text-sm font-medium"
                          style={{ color: row.label === 'Durum' ? STATUS_COLOR[jobStatus.status] ?? '#e8edf5' : '#e8edf5' }}>
                          {row.value}
                        </p>
                      </div>
                    ))}
                  </div>

                  <button
                    onClick={() => window.open(`${API_BASE_URL}/ansible/awx/job/${jobId}/stdout`, '_blank')}
                    className="px-3 py-1.5 text-xs rounded-lg border border-white/[0.08] text-slate-400 hover:text-[#e8edf5] hover:bg-white/[0.03] transition-colors">
                    Çıktıyı Gör →
                  </button>
                </div>
              )}
            </div>
          )}

          {/* ── Output: Ad-hoc / Playbook results ───────────────────────── */}
          {result && (
            <div className={card}>
              {/* Header */}
              <div className="px-5 py-3.5 border-b border-white/[0.06] flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <p className="text-sm font-medium text-[#e8edf5]">Çıktılar</p>
                  {successCount > 0 && (
                    <span className="text-xs px-2 py-0.5 rounded-full font-medium"
                      style={{ background: `rgba(${rgb(NEON.green)},0.12)`, color: NEON.green, border: `1px solid rgba(${rgb(NEON.green)},0.25)` }}>
                      {successCount} başarılı
                    </span>
                  )}
                  {failCount > 0 && (
                    <span className="text-xs px-2 py-0.5 rounded-full font-medium"
                      style={{ background: `rgba(${rgb(NEON.red)},0.12)`, color: NEON.red, border: `1px solid rgba(${rgb(NEON.red)},0.25)` }}>
                      {failCount} hata
                    </span>
                  )}
                </div>
                <button onClick={() => setResult(null)}
                  className="text-slate-600 hover:text-slate-300 text-lg leading-none transition-colors">×</button>
              </div>

              {/* Per-server output */}
              <div className="divide-y divide-white/[0.04] max-h-96 overflow-y-auto">
                {result.results && Object.entries(result.results).map(([srv, res]: [string, any]) => (
                  <div key={srv} className="px-5 py-3">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                        style={{ background: res.rc === 0 ? NEON.green : NEON.red }} />
                      <span className="text-xs font-medium text-[#e8edf5]">{srv}</span>
                      <span className="text-[10px] font-mono text-slate-600 ml-auto">
                        rc={res.rc}
                      </span>
                    </div>
                    <pre className="text-[11px] font-mono text-slate-400 whitespace-pre-wrap bg-[#080d16] rounded-lg p-3 leading-relaxed">
                      {res.stdout || res.stderr || '(çıktı yok)'}
                    </pre>
                  </div>
                ))}
              </div>

              {/* Raw output toggle */}
              {result.stdout && (
                <details className="border-t border-white/[0.06]">
                  <summary className="px-5 py-2.5 text-xs text-slate-600 cursor-pointer hover:text-slate-400 select-none">
                    Ham çıktı
                  </summary>
                  <pre className="px-5 pb-4 text-[11px] font-mono text-slate-400 whitespace-pre-wrap">
                    {result.stdout}
                  </pre>
                </details>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default Ansible
