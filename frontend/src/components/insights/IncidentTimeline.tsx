import React, { useState } from 'react'
import { useT } from '../../i18n/LocaleProvider'
import { useInsights } from './insightsKit'

const SEV_DOT: Record<string, string> = {
  critical: 'bg-red-500', high: 'bg-amber-500', medium: 'bg-amber-400', warning: 'bg-amber-400', low: 'bg-blue-500', info: 'bg-slate-500',
}

/** Sanallaştırma (virt-insights) veya OpenShift (ocp-insights) olayı için zaman çizelgesi + kök neden adayları (deterministik; LLM yok). */
export default function IncidentTimeline({ incidentId, base = 'virt-insights' }: { incidentId: number; base?: 'virt-insights' | 'ocp-insights' }) {
  const t = useT()
  const [win, setWin] = useState(120)
  const q = useInsights<any>(base, `/incident-timeline/${incidentId}?before_min=${win}&after_min=60`)
  const items: any[] = q.data?.items || []
  const cands: any[] = q.data?.candidates || []
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <p className="text-xs font-medium text-blue-400">{t('vi_tl_title')}</p>
        <select value={win} onChange={e => setWin(Number(e.target.value))} className="rounded bg-black/30 border border-white/[0.08] px-1.5 py-0.5 text-[11px] text-slate-300">
          {[30, 120, 360, 1440].map(m => <option key={m} value={m}>{t('vi_tl_before', { n: m >= 60 ? `${m / 60} h` : `${m} min` })}</option>)}
        </select>
      </div>
      <div className="rounded-lg p-3 space-y-3 bg-black/20 border border-blue-500/20">
        {q.isLoading && <div className="text-xs text-slate-400">{t('loading')}</div>}
        {q.error && <div className="text-xs text-red-300">{(q.error as Error).message}</div>}
        {q.data && (
          <>
            {q.data.applicable === false && <div className="text-xs text-slate-400">{q.data.note}</div>}
            {base === 'ocp-insights' && q.data.live && q.data.live.ok === false && (
              <div className="text-[11px] text-amber-300">{t('oi_tl_live_off', { err: q.data.live.error || '-' })}</div>
            )}
            <div className="text-[10px] text-slate-500">
              {[...(q.data.scope?.hosts || []), ...(q.data.scope?.vms || []), ...(q.data.scope?.datastores || [])].join(', ') || t('vi_tl_no_scope')}
            </div>
            {cands.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[11px] text-slate-400">{t('vi_tl_candidates')}</div>
                {cands.slice(0, 4).map(c => (
                  <details key={c.id} className="text-xs">
                    <summary className="cursor-pointer text-slate-200">
                      <span className="font-mono text-blue-300 mr-2">%{Math.round((c.confidence || 0) * 100)}</span>{c.title}
                    </summary>
                    <div className="pl-6 pt-1 space-y-0.5 text-slate-400">
                      {(c.evidence || []).map((e: string, i: number) => <div key={i}>• {e}</div>)}
                      {(c.verify || []).length > 0 && <div className="text-slate-500 pt-1">{t('vi_tl_verify')}:</div>}
                      {(c.verify || []).map((v: string, i: number) => <div key={`v${i}`} className="text-slate-500">→ {v}</div>)}
                    </div>
                  </details>
                ))}
              </div>
            )}
            <div className="max-h-72 overflow-y-auto space-y-1">
              {items.length === 0 && <div className="text-xs text-slate-500">{t('vi_tl_empty')}</div>}
              {items.map((it, i) => (
                <div key={i} className="flex items-start gap-2 text-[11px]">
                  <span className={`mt-1 w-1.5 h-1.5 rounded-full flex-shrink-0 ${SEV_DOT[it.severity] || 'bg-slate-500'}`} />
                  <span className="font-mono text-slate-500 whitespace-nowrap">{it.t ? new Date(it.t).toLocaleTimeString() : ''}</span>
                  <span className="text-slate-500 whitespace-nowrap">{it.source}</span>
                  <span className="text-slate-300 break-words">{it.title}</span>
                </div>
              ))}
            </div>
            <div className="text-[10px] text-slate-500">{t('vi_tl_note')}</div>
          </>
        )}
      </div>
    </div>
  )
}
