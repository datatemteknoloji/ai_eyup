import React, { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import { useT } from '../i18n/LocaleProvider'

const WIN_API = `${API_BASE_URL}/windows`

interface WinServer {
  id: number
  name: string
  hostname?: string
  ip_address: string
  status: string
  ai_ready: boolean
  winrm_configured: boolean
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

const card = 'bg-[#0d1422] border border-white/[0.07] rounded-[10px]'
const inputCls = 'w-full bg-[#080d16] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-[#e8edf5] placeholder-slate-600 focus:outline-none focus:border-blue-500/60'

const PS_SCRIPTS = [
  { labelKey: 'ans_ps_uptime' as const, script: '(Get-CimInstance Win32_OperatingSystem).LastBootUpTime' },
  { labelKey: 'ans_ps_disk' as const, script: 'Get-PSDrive -PSProvider FileSystem | Select-Object Name,Used,Free' },
  { labelKey: 'ans_ps_services' as const, script: "Get-Service | Where-Object Status -eq 'Running' | Select-Object -First 20 Name,Status" },
]

const WindowsAnsible: React.FC = () => {
  const t = useT()
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [search, setSearch]           = useState('')
  const [script, setScript]           = useState('')
  const [result, setResult]           = useState<any>(null)

  const { data: allServers = [] } = useQuery<WinServer[]>({
    queryKey: ['windows-servers'],
    queryFn: async () => {
      const res = await fetch(`${WIN_API}/servers`)
      if (!res.ok) throw new Error(t('ans_win_load_fail'))
      return res.json()
    },
  })

  const readyServers = allServers.filter(
    s => s.ai_ready && s.status === 'ONLINE' && s.ip_address?.trim()
  )

  const filtered = search
    ? readyServers.filter(s => {
        const q = search.toLowerCase()
        return (
          s.name.toLowerCase().includes(q) ||
          s.ip_address?.toLowerCase().includes(q) ||
          s.hostname?.toLowerCase().includes(q)
        )
      })
    : readyServers

  const runAdHoc = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${WIN_API}/adhoc`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ server_ids: selectedIds, script }),
      })
      if (!res.ok) throw new Error(t('ans_ps_fail'))
      return res.json()
    },
    onSuccess: data => setResult(data),
    onError: (err: Error) => alert(t('ans_err', { msg: err.message })),
  })

  const toggle = (id: number) =>
    setSelectedIds(prev => (prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]))

  const successCount = result?.results
    ? Object.values(result.results).filter((r: any) => r.rc === 0).length
    : 0
  const failCount = result?.failed?.length ?? 0

  const canRun = selectedIds.length > 0 && !!script.trim() && !runAdHoc.isPending

  return (
    <div className="flex flex-col gap-6 min-h-0">
      {/* Page header */}
      <div>
        <h1 className="text-xl font-semibold text-[#e8edf5]">{t('ans_win_title')}</h1>
        <p className="text-sm text-slate-500 mt-0.5">{t('ans_win_subtitle')}</p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[320px_1fr] gap-5">
        {/* ── Left: Server selection ─────────────────────────────────────── */}
        <div className={`${card} flex flex-col min-h-0`}>
          <div className="px-5 py-4 border-b border-white/[0.06] flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">{t('ans_win_servers')}</p>
              <p className="text-sm font-semibold text-[#e8edf5] mt-0.5">
                {selectedIds.length > 0
                  ? <span style={{ color: NEON.blue }}>{t('selected_n', { n: selectedIds.length })}</span>
                  : <span className="text-slate-500">{t('ans_none_selected')}</span>
                }
                <span className="text-slate-600 font-normal">{t('ans_n_ready', { n: readyServers.length })}</span>
              </p>
            </div>
            <div className="flex gap-1.5">
              <button onClick={() => setSelectedIds(filtered.map(s => s.id))}
                className="px-2.5 py-1 text-xs rounded-lg text-blue-400 border border-blue-500/30 bg-blue-500/10 hover:bg-blue-500/20 transition-colors">
                {t('filter_all')}
              </button>
              <button onClick={() => setSelectedIds([])}
                className="px-2.5 py-1 text-xs rounded-lg text-slate-400 border border-white/[0.06] hover:bg-white/[0.04] transition-colors">
                {t('pkg_clear')}
              </button>
            </div>
          </div>

          <div className="px-4 pt-3 pb-2">
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={t('ans_search')}
              className={inputCls}
            />
          </div>

          <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-0.5 max-h-[320px] xl:max-h-none">
            {filtered.length === 0 ? (
              <div className="py-8 text-center text-slate-600 text-sm">
                {search ? t('ans_no_search', { q: search }) : t('ans_no_winrm')}
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
          <div className={`${card} p-5 space-y-4`}>
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-xs text-slate-500 font-medium uppercase tracking-wider">{t('ans_ps_script')}</label>
                <div className="flex gap-1.5">
                  {PS_SCRIPTS.map(ex => (
                    <button key={ex.labelKey} onClick={() => setScript(ex.script)}
                      className="px-2 py-0.5 text-[11px] rounded-md text-slate-400 border border-white/[0.06] hover:bg-white/[0.04] hover:text-[#e8edf5] transition-colors">
                      {t(ex.labelKey)}
                    </button>
                  ))}
                </div>
              </div>
              <textarea
                value={script}
                onChange={e => setScript(e.target.value)}
                rows={6}
                placeholder={t('ans_ps_ph')}
                className={`${inputCls} font-mono text-xs leading-relaxed resize-y`}
              />
            </div>

            <div className="flex items-center gap-3 pt-1">
              <button
                onClick={() => runAdHoc.mutate()}
                disabled={!canRun}
                className="px-5 py-2 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-2">
                {runAdHoc.isPending && (
                  <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                )}
                {runAdHoc.isPending ? t('ans_running') : t('ans_run_cmd')}
              </button>
              {selectedIds.length === 0 && (
                <span className="text-xs text-slate-600">{t('ans_pick_left')}</span>
              )}
            </div>
          </div>

          {/* ── Output ────────────────────────────────────────────────────── */}
          {result && (
            <div className={card}>
              <div className="px-5 py-3.5 border-b border-white/[0.06] flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <p className="text-sm font-medium text-[#e8edf5]">{t('ans_outputs')}</p>
                  {successCount > 0 && (
                    <span className="text-xs px-2 py-0.5 rounded-full font-medium"
                      style={{ background: `rgba(${rgb(NEON.green)},0.12)`, color: NEON.green, border: `1px solid rgba(${rgb(NEON.green)},0.25)` }}>
                      {t('ans_n_ok', { n: successCount })}
                    </span>
                  )}
                  {failCount > 0 && (
                    <span className="text-xs px-2 py-0.5 rounded-full font-medium"
                      style={{ background: `rgba(${rgb(NEON.red)},0.12)`, color: NEON.red, border: `1px solid rgba(${rgb(NEON.red)},0.25)` }}>
                      {t('ans_n_err', { n: failCount })}
                    </span>
                  )}
                </div>
                <button onClick={() => setResult(null)}
                  className="text-slate-600 hover:text-slate-300 text-lg leading-none transition-colors">×</button>
              </div>

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
                      {res.stdout || res.stderr || t('ans_no_out')}
                    </pre>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default WindowsAnsible
