import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'

/**
 * Faz 3a — «Donanım günlükleri» kartı (Linux/Windows çekmecesi + ESXi host paneli).
 * Kaynak: vCenter SEL/vmkernel ve mevcut Linux/Windows log toplayıcıları; iLO/iDRAC'e BAĞLANILMAZ.
 * - Özellik kapalıysa (`hw_host_logs_enabled`) veya bu hedef için kayıt yoksa HİÇ render edilmez.
 * - Salt-okunur: düğme yalnız listeyi aç/kapatır. Metinler sunucuda maskelenmiştir (IP/UUID/MAC).
 */
const SEV_CLS: Record<string, string> = {
  critical: 'bg-red-500/15 text-red-300 border-red-500/30',
  warning: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  info: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
}
const COLLAPSED = 5

// «14:52» (bugünse) veya «27.10.2026 14:52»
const fmtRun = (iso?: string | null): string => {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return d.toDateString() === new Date().toDateString() ? hm : `${d.toLocaleDateString()} ${hm}`
}

/** `showEmpty`: özellik açıkken kayıt olmasa da kısa bir «kayıt yok · son toplama HH:MM» satırı gösterir (ESXi host paneli). */
export const HwHostLogsCard: React.FC<{ kind: 'server' | 'esxi' | 'hw'; id: number; days?: number; showEmpty?: boolean }> = ({ kind, id, days = 7, showEmpty = false }) => {
  const t = useT()
  const [open, setOpen] = useState(false)
  const q = useQuery<any>({
    queryKey: ['hw-host-logs', kind, id, days],
    enabled: !!id,
    retry: false,
    staleTime: 60_000,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hw/host-logs?kind=${kind}&id=${id}&days=${days}&limit=50`)
      if (!r.ok) return { available: false, items: [] }
      return r.json()
    },
  })
  const items: any[] = q.data?.items || []
  const runTxt = q.data?.last_run_at ? t('hwlog_last_run', { t: fmtRun(q.data.last_run_at) }) : t('hwlog_never_run')
  const runErr = Number(q.data?.last_run_errors || 0)
  if (showEmpty && q.data?.enabled && items.length === 0) {
    return (
      <div data-testid="hw-host-logs-empty" className="text-[11px] text-slate-500 flex flex-wrap items-center gap-x-2">
        <span className="text-slate-400">{t('hwlog_title')}:</span>
        <span>{t('hwlog_none', { n: q.data.days ?? days })}</span>
        <span>· {runTxt}</span>
        {runErr > 0 ? <span className="text-amber-400">· {t('hwlog_run_errors', { n: runErr })}</span> : null}
      </div>
    )
  }
  if (!q.data?.available || items.length === 0) return null
  const counts = q.data.counts || {}
  const shown = open ? items : items.slice(0, COLLAPSED)
  return (
    <div data-testid="hw-host-logs-card" className="bg-cyber-card/50 rounded-xl border border-white/[0.06] p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-medium text-white">{t('hwlog_title')}</h3>
          <div className="text-[11px] text-slate-500">{t('hwlog_sub')} · {t('hwlog_window', { n: q.data.days ?? days })}</div>
        </div>
        <div className="flex items-center gap-1.5">
          {(['critical', 'warning'] as const).filter(s => counts[s]).map(s => (
            <span key={s} className={`text-[11px] px-1.5 py-0.5 rounded-sm border ${SEV_CLS[s]}`}>
              {t(`hwlog_sev_${s}` as any)} {counts[s]}
            </span>
          ))}
        </div>
      </div>
      <div className="space-y-1.5">
        {shown.map((it: any) => (
          <div key={it.id} data-testid="hw-host-log-row" className="text-xs text-slate-300 flex items-start gap-2">
            <span className={`shrink-0 px-1.5 rounded-sm border text-[10px] ${SEV_CLS[it.severity] || SEV_CLS.info}`}>
              {t(`hwlog_sev_${it.severity}` as any)}
            </span>
            <span className="shrink-0 text-[10px] text-slate-400 border border-white/10 rounded-sm px-1">
              {t(`hwlog_cat_${it.category}` as any)}
            </span>
            <span className="min-w-0 flex-1 wrap-break-word" title={it.message}>{it.message}</span>
            <span className="shrink-0 text-[10px] text-slate-500 whitespace-nowrap">
              {it.occurrences > 1 ? `${it.occurrences}× · ` : ''}
              {it.last_seen_at ? t('hwlog_last', { d: new Date(it.last_seen_at).toLocaleString() }) : ''}
              {' · '}{t(`hwlog_src_${it.source}` as any)}
            </span>
          </div>
        ))}
      </div>
      {items.length > COLLAPSED && (
        <button type="button" onClick={() => setOpen(o => !o)} className="text-[11px] text-blue-300 hover:text-blue-200">
          {open ? t('hwlog_less') : t('hwlog_more', { n: items.length })}
        </button>
      )}
      <div className="text-[10px] text-slate-600">
        {runTxt}{runErr > 0 ? ` · ${t('hwlog_run_errors', { n: runErr })}` : ''} · {t('hwlog_footer')}
      </div>
    </div>
  )
}

export default HwHostLogsCard
