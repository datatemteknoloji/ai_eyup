/**
 * Yönetici Raporu — tüm ortamlar (Linux, Windows, Sanallaştırma, OpenShift, Exadata)
 * için tek sayfalık özet; Markdown indirme ve yazdır / PDF.
 */
import { useQuery } from '@tanstack/react-query'
import { Download, FileText, Printer, RefreshCw } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useT } from '../i18n/LocaleProvider'

type Env = {
  key: string
  label: string
  inventory: string
  monitoring: string
  critical: number
  warning: number
  health_score: number | null
  grade: string
  present: boolean
}
type Alert = { severity?: string; platform?: string; server_name?: string; title?: string }
type Incident = { id: number; severity?: string; platform?: string; title?: string; server_name?: string }
type Report = {
  generated_at: string
  overall: { health_score?: number; grade?: string; label?: string; critical_total?: number; warning_total?: number; open_incidents?: number; total_servers?: number }
  environments: Env[]
  top_alerts: Alert[]
  open_incidents: Incident[]
  recommendations: string[]
  markdown: string
}

const sevCls = (s?: string) =>
  s === 'critical' || s === 'emergency' ? 'text-red-400' : s === 'warning' ? 'text-amber-300' : 'text-slate-400'

export default function ExecutiveReports() {
  const t = useT()
  const q = useQuery<Report>({
    queryKey: ['executive-report'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/ops/executive-report`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    },
    staleTime: 60_000,
  })
  const d = q.data

  const download = () => {
    if (!d) return
    const blob = new Blob([d.markdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `yonetici-raporu-${new Date().toISOString().slice(0, 10)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-5 animate-fade-in pb-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-white inline-flex items-center gap-2">
            <FileText size={18} /> {t('exec_rpt_title')}
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">{t('exec_rpt_sub')}</p>
        </div>
        <div className="flex items-center gap-2 print:hidden">
          <button type="button" onClick={() => q.refetch()} disabled={q.isFetching}
            className="px-3 py-1.5 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] text-xs text-slate-200 inline-flex items-center gap-1.5 disabled:opacity-50">
            <RefreshCw size={13} className={q.isFetching ? 'animate-spin' : ''} /> {t('exec_rpt_generate')}
          </button>
          <button type="button" onClick={download} disabled={!d}
            className="px-3 py-1.5 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] text-xs text-slate-200 inline-flex items-center gap-1.5 disabled:opacity-50">
            <Download size={13} /> Markdown
          </button>
          <button type="button" onClick={() => window.print()} disabled={!d}
            className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-xs text-white inline-flex items-center gap-1.5 disabled:opacity-50">
            <Printer size={13} /> {t('exec_rpt_print')}
          </button>
        </div>
      </div>

      {q.isLoading && <div className="text-sm text-slate-500">{t('exec_rpt_loading')}</div>}
      {q.isError && <div className="text-sm text-red-400">{t('exec_rpt_error')}</div>}

      {d && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {[
              [t('exec_rpt_score'), `${d.overall.health_score ?? '—'} (${d.overall.grade ?? '—'})`],
              [t('exec_rpt_critical'), d.overall.critical_total ?? 0],
              [t('exec_rpt_warning'), d.overall.warning_total ?? 0],
              [t('exec_rpt_open_inc'), d.overall.open_incidents ?? 0],
              [t('exec_rpt_servers'), d.overall.total_servers ?? 0],
            ].map(([k, v]) => (
              <div key={String(k)} className="cyber-card p-4">
                <div className="text-[11px] text-slate-500">{k}</div>
                <div className="text-xl font-semibold text-white mt-1 tabular-nums">{v}</div>
              </div>
            ))}
          </div>

          <div className="cyber-card p-5 overflow-x-auto">
            <h2 className="text-sm font-medium text-white mb-3">{t('exec_rpt_envs')}</h2>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-500">
                  <th className="py-1.5 pr-3">{t('exec_rpt_env')}</th>
                  <th className="pr-3">{t('exec_rpt_inventory')}</th>
                  <th className="pr-3">{t('exec_rpt_monitoring')}</th>
                  <th className="pr-3 text-right">{t('exec_rpt_critical')}</th>
                  <th className="pr-3 text-right">{t('exec_rpt_warning')}</th>
                  <th className="text-right">{t('exec_rpt_score')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.05]">
                {d.environments.map((e) => (
                  <tr key={e.key} className={e.present || e.critical || e.warning ? 'text-slate-200' : 'text-slate-600'}>
                    <td className="py-2 pr-3 font-medium">{e.label}</td>
                    <td className="pr-3">{e.present ? e.inventory : '—'}</td>
                    <td className="pr-3">{e.present ? e.monitoring : '—'}</td>
                    <td className="pr-3 text-right tabular-nums text-red-300">{e.critical}</td>
                    <td className="pr-3 text-right tabular-nums text-amber-300">{e.warning}</td>
                    <td className="text-right tabular-nums">{e.health_score ?? '—'} {e.health_score != null ? `(${e.grade})` : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <div className="cyber-card p-5">
              <h2 className="text-sm font-medium text-white mb-3">{t('exec_rpt_alerts')}</h2>
              {d.top_alerts.length === 0 ? <div className="text-xs text-slate-500">—</div> : (
                <ul className="space-y-1.5 text-xs">
                  {d.top_alerts.map((a, i) => (
                    <li key={i} className="text-slate-300">
                      <span className={`font-semibold uppercase ${sevCls(a.severity)}`}>{a.severity}</span>{' '}
                      <span className="text-slate-500">{a.platform} · {a.server_name || '—'}</span> — {a.title}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="cyber-card p-5">
              <h2 className="text-sm font-medium text-white mb-3">{t('exec_rpt_incidents')}</h2>
              {d.open_incidents.length === 0 ? <div className="text-xs text-slate-500">—</div> : (
                <ul className="space-y-1.5 text-xs">
                  {d.open_incidents.map((i) => (
                    <li key={i.id} className="text-slate-300">
                      <span className={`font-semibold uppercase ${sevCls(i.severity)}`}>#{i.id}</span>{' '}
                      <span className="text-slate-500">{i.platform}</span> — {i.title}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="cyber-card p-5">
            <h2 className="text-sm font-medium text-white mb-3">{t('exec_rpt_recs')}</h2>
            <ol className="list-decimal pl-5 space-y-1 text-xs text-slate-300">
              {d.recommendations.map((r, i) => <li key={i}>{r}</li>)}
            </ol>
            <p className="text-[10px] text-slate-600 mt-3">{t('exec_rpt_generated', { at: d.generated_at })}</p>
          </div>
        </>
      )}
    </div>
  )
}
