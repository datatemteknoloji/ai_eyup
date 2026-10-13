import React, { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useT } from '../../i18n/LocaleProvider'
import { MethodBadge } from './MethodBadge'
import { fmt, pctTone } from './insightsKit'
import { TermHint } from './InfoDot'

/** Backend gerekçe kodları (tek kelime). Arayüz yalnız backend'in döndürdüğü kodu çevirir; kendi hesap yapmaz. */
const LIMIT_KEYS: Record<string, string> = {
  memory: 'vi_lim_memory', cpu: 'vi_lim_cpu', ha: 'vi_lim_ha', datastore: 'vi_lim_datastore',
  fragmentation: 'vi_lim_fragmentation', no_host: 'vi_lim_no_host', cores: 'vi_lim_cores',
  anti_affinity: 'vi_lim_anti_affinity', vcpu_ratio: 'vi_lim_vcpu_ratio', ha_slots: 'vi_lim_ha_slots',
}

type Row = any

/** Satırdaki yerleşimlerden benzersiz host listesi ("esx01 ×2"). */
export function placedHosts(r: Row): { host: string; n: number }[] {
  const m = new Map<string, number>()
  for (const p of r?.placement?.placed || []) m.set(p.host, (m.get(p.host) || 0) + 1)
  return Array.from(m.entries()).map(([host, n]) => ({ host, n }))
}

/** Gerekçe çipi + (i). Toplu yerleşim ekranı da kullanır. */
export function LimitChip({ code, tone }: { code: string; tone: 'fail' | 'warn' }) {
  const t = useT()
  const key = LIMIT_KEYS[code]
  return (
    <span data-testid={`lim-${code}`}
      className={`inline-block rounded border px-1.5 py-0.5 text-[11px] font-medium ${tone === 'fail'
        ? 'border-red-500/30 bg-red-500/10 text-red-300' : 'border-amber-500/30 bg-amber-500/10 text-amber-200'}`}>
      {key ? t(key as any) : code}
      {key && <TermHint k={`lim_${code}`} />}
    </span>
  )
}

function ResultCell({ r, count }: { r: Row; count: number }) {
  const t = useT()
  const st: string = r.status || (r.fits ? 'ok' : 'fail')
  const max: number | null | undefined = r.max_fit
  if (st === 'fail') {
    return (
      <div data-testid="res-fail">
        <span className="text-red-300">❌</span>
        {max != null && <div className="text-[11px] text-slate-500">{t('vi_wi_max', { n: max })}</div>}
      </div>
    )
  }
  return (
    <div data-testid={st === 'warn' ? 'res-warn' : 'res-ok'}>
      <span className={st === 'warn' ? 'text-amber-300' : 'text-emerald-400'}>{st === 'warn' ? '⚠️' : '✅'} {max != null ? t('vi_wi_n', { n: max }) : ''}</span>
      <div className="text-[11px] text-slate-500">{t('vi_wi_requested_fit', { n: count })}</div>
    </div>
  )
}

function Detail({ r, count }: { r: Row; count: number }) {
  const t = useT()
  const pl = r.placement
  return (
    <div className="px-3 py-3 space-y-2 text-xs">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <div className="text-slate-500">{t('vi_cap_eff_mem')}</div>
          <div className="font-mono">%{fmt(r.before?.memory_effective_pct)} → <span className={pctTone(r.after?.memory_effective_pct, 75, 85)}>%{fmt(r.after?.memory_effective_pct)}</span></div>
        </div>
        <div>
          <div className="text-slate-500 inline-flex items-center">N+1<TermHint k="n1" /></div>
          <div className="font-mono">%{fmt(r.before?.n1_memory_pct)} → %{fmt(r.after?.n1_memory_pct)}</div>
        </div>
        <div>
          <div className="text-slate-500">Datastore</div>
          <div className="font-mono">{r.datastore ? `${r.datastore.name} (%${fmt(r.datastore.usage_after_pct)})` : '—'}</div>
        </div>
      </div>
      {r.confidence && (
        <div><span className="text-slate-500">{t('vi_whatif_conf')}: </span>
          <span className={r.confidence === 'low' ? 'text-amber-400' : 'text-slate-300'}>{t(`vi_whatif_conf_${r.confidence}` as any)}</span>
          {pl?.placed && <span className="text-slate-500"> · {t('vi_whatif_placed', { n: pl.placed.length, total: count })}</span>}
        </div>
      )}
      {(pl?.host_free || []).length > 0 && (
        <div>
          <div className="text-slate-500">{t('vi_wi_host_free')}</div>
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 font-mono text-slate-300">
            {pl.host_free.map((h: any) => <span key={h.host}>{h.host}: {fmt(h.free_gb)} GB</span>)}
          </div>
        </div>
      )}
      {(r.reasons || []).length > 0 && (
        <div>
          <div className="text-slate-500">{t('vi_whatif_reasons')}</div>
          {r.reasons.map((x: string, i: number) => <div key={i} className="text-slate-400">• {x}</div>)}
        </div>
      )}
      {(pl?.notes || []).map((n: string, i: number) => <div key={i} className="text-[11px] text-slate-500">• {n}</div>)}
    </div>
  )
}

export default function WhatIfResults({ results, count, assumptions }: { results: Row[]; count: number; assumptions?: string[] }) {
  const t = useT()
  const [filter, setFilter] = useState<'all' | 'fit' | 'nofit'>('all')
  const [open, setOpen] = useState<string | null>(null)
  const fitN = results.filter(r => r.fits).length
  const rows = useMemo(
    () => results.filter(r => filter === 'all' || (filter === 'fit' ? r.fits : !r.fits)),
    [results, filter],
  )
  const chip = (id: 'all' | 'fit' | 'nofit', label: string, n: number) => (
    <button type="button" data-testid={`wi-filter-${id}`} onClick={() => setFilter(id)}
      className={`rounded-full border px-2.5 py-0.5 text-xs ${filter === id
        ? 'border-blue-500/60 bg-blue-600/20 text-blue-200' : 'border-white/[0.1] text-slate-400 hover:text-slate-200'}`}>
      {label} <span className="font-mono">{n}</span>
    </button>
  )
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {chip('all', t('vi_wi_filter_all'), results.length)}
        {chip('fit', t('vi_wi_filter_fit'), fitN)}
        {chip('nofit', t('vi_wi_filter_nofit'), results.length - fitN)}
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-white/[0.06]">
            <th className="px-3 py-2 w-6" />
            <th className="px-3 py-2">{t('vi_scope_cluster')}</th>
            <th className="px-3 py-2"><span className="inline-flex items-center gap-1">{t('vi_whatif_verdict')}<MethodBadge id="cap.sim.host_placement" /><TermHint k="result" /></span></th>
            <th className="px-3 py-2"><span className="inline-flex items-center">{t('vi_wi_limiting')}<TermHint k="limiting" /></span></th>
            <th className="px-3 py-2">{t('vi_wi_hosts')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={5} className="py-6 text-center text-slate-500">{t('vi_no_rows')}</td></tr>}
          {rows.map(r => {
            const key = `${r.hypervisor_id}:${r.cluster}`
            const isOpen = open === key
            const hosts = placedHosts(r)
            return (
              <React.Fragment key={key}>
                <tr data-testid="wi-row" className="border-b border-white/[0.04] hover:bg-white/[0.02] cursor-pointer"
                  onClick={() => setOpen(isOpen ? null : key)}>
                  <td className="px-3 py-2 text-slate-500">{isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                  <td className="px-3 py-2">
                    <div className="font-mono text-xs text-white">{r.path || `${r.hypervisor} / ? / ${r.cluster}`}</div>
                    {r.standalone && <div className="text-[11px] text-slate-500">{t('vi_wi_standalone')}</div>}
                  </td>
                  <td className="px-3 py-2"><ResultCell r={r} count={count} /></td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {(r.limiting || []).map((c: string) => <LimitChip key={`l-${c}`} code={c} tone="fail" />)}
                      {(r.warn_codes || []).filter((c: string) => !(r.limiting || []).includes(c)).map((c: string) => <LimitChip key={`w-${c}`} code={c} tone="warn" />)}
                      {!(r.limiting || []).length && !(r.warn_codes || []).length && <span className="text-slate-600">—</span>}
                    </div>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-300">
                    {hosts.length ? hosts.map(h => (h.n > 1 ? `${h.host} ×${h.n}` : h.host)).join(', ') : <span className="text-slate-600">—</span>}
                  </td>
                </tr>
                {isOpen && <tr className="border-b border-white/[0.04] bg-black/20"><td /><td colSpan={4}><Detail r={r} count={count} /></td></tr>}
              </React.Fragment>
            )
          })}
        </tbody>
      </table>
      <div className="text-[11px] text-slate-500 space-y-0.5">{(assumptions || []).map((a, i) => <div key={i}>• {a}</div>)}</div>
    </div>
  )
}
