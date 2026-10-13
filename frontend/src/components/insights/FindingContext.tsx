import React from 'react'
import { useT } from '../../i18n/LocaleProvider'
import { SeverityBadge } from '../aiops/ui'
import { TermHint } from './InfoDot'
import SmartLink from './SmartLink'

type Rel = { id: number; check_id: string; category: string; severity: string; title: string; detail: string | null }

export type FindingCtx = {
  guide?: {
    guides: { key: string; title: string; cause: string; impact: string; steps: string[] }[]
    vendor?: string | null
    official_links?: { id: string; title_tr?: string; title_en?: string; url: string }[]
  } | null
  related?: Rel[]
  /** (a) aynı olay (aynı kök) ve (b) aynı host'taki diğer açık bulgular; yoksa (eski backend) `related` tek liste çizilir. */
  related_event?: Rel[]
  related_other?: Rel[]
  event?: { key: string; family: string; member_ids: number[]; representative_id: number } | null
  impact?: {
    available: boolean; reason?: string | null; verdict?: string; status?: string; vms?: number; memory_gb?: number
    unplaced?: number; remaining_hosts?: number; after_memory_pct?: number | null; threshold_pct?: number; notes?: string[]
    hypervisor_id?: number; cluster?: string; host?: string
  } | null
}

const TONE: Record<string, string> = { fit: 'text-emerald-400', tight: 'text-amber-400', fail: 'text-red-400', no_vm: 'text-slate-300' }
const ICON: Record<string, string> = { fit: '✅', tight: '⚠️', fail: '❌', no_vm: '✅' }

function RelatedList({ items, title, testid, hint, muted, onOpenFinding, openable }:
  { items: Rel[]; title: string; testid: string; hint?: string; muted?: boolean; onOpenFinding?: (id: number) => void; openable?: Set<number> }) {
  return (
    <div data-testid={testid} className="space-y-1">
      <div className="text-[11px] uppercase tracking-wider text-slate-500 inline-flex items-center">{title}{hint && <TermHint k={hint} />}</div>
      {items.map(r => (
        <div key={r.id} className={`flex items-center gap-2 text-xs ${muted ? 'text-slate-400' : 'text-slate-300'}`}>
          <SeverityBadge severity={r.severity} />
          {openable?.has(r.id)
            ? <button type="button" className="text-blue-300 hover:underline text-left" onClick={e => { e.stopPropagation(); onOpenFinding?.(r.id) }}>{r.title}</button>
            : <span>{r.title}</span>}
          {r.detail && <span className="text-slate-500 truncate max-w-[24rem]" title={r.detail}>{r.detail}</span>}
        </div>
      ))}
    </div>
  )
}

/** Bulgu bağlamı (kural tabanlı, AI değil): host düşerse etki · aynı host'ta diğer bulgular · genel rehber. */
export default function FindingContext({ ctx, onOpenFinding, openable }: { ctx: FindingCtx; onOpenFinding?: (id: number) => void; openable?: Set<number> }) {
  const t = useT()
  const imp = ctx.impact
  const rel = ctx.related || []
  const split = ctx.related_event !== undefined || ctx.related_other !== undefined
  const evt = ctx.related_event || []
  const oth = ctx.related_other || []
  const g = ctx.guide
  if (!imp && !rel.length && !evt.length && !oth.length && !g) return null
  return (
    <div className="space-y-3 rounded border border-white/[0.06] bg-black/20 p-3" data-testid="finding-context">
      {imp && imp.available && imp.verdict && (
        <div data-testid="fc-impact" className="space-y-0.5">
          <div className="text-[11px] uppercase tracking-wider text-slate-500">{t('vi_fc_impact')}</div>
          <div className={`text-sm font-medium ${TONE[imp.verdict] || ''}`}>{ICON[imp.verdict]} {t(`vi_hf_verdict_${imp.verdict}` as any)}{['fit', 'tight', 'fail'].includes(imp.verdict) && <TermHint k={imp.verdict} />}</div>
          <div className="text-xs text-slate-400 font-mono">
            {t('vi_hf_summary', {
              n: imp.vms ?? 0, mem: imp.memory_gb ?? 0, hosts: imp.remaining_hosts ?? 0,
              after: imp.after_memory_pct == null ? '—' : imp.after_memory_pct, thr: imp.threshold_pct ?? '—',
            })}
          </div>
          {(imp.notes || []).slice(0, 1).map(n => <div key={n} className="text-[11px] text-slate-500">{n}</div>)}
          {imp.hypervisor_id != null && imp.cluster && imp.host && (
            <SmartLink data-testid="fc-impact-link" className="text-[11px] text-blue-300 hover:underline"
              to={`/virt/capacity?tab=hostfail&hv=${imp.hypervisor_id}&cluster=${encodeURIComponent(imp.cluster)}&host=${encodeURIComponent(imp.host)}`}>{t('vi_fc_open_n1')}</SmartLink>
          )}
        </div>
      )}
      {imp && !imp.available && imp.reason && <div className="text-[11px] text-slate-500" data-testid="fc-impact-na">{t('vi_fc_impact_na', { reason: imp.reason })}</div>}
      {split ? (
        <>
          {evt.length > 0 && <RelatedList items={evt} title={t('vi_fc_related_event', { n: evt.length })} testid="fc-related-event" hint="fc_event"
            onOpenFinding={onOpenFinding} openable={openable} />}
          {oth.length > 0 && <RelatedList items={oth} title={t('vi_fc_related_other', { n: oth.length })} testid="fc-related-other" hint="fc_other"
            onOpenFinding={onOpenFinding} openable={openable} muted />}
        </>
      ) : rel.length > 0 && (
        <RelatedList items={rel} title={t('vi_fc_related', { n: rel.length })} testid="fc-related" onOpenFinding={onOpenFinding} openable={openable} />
      )}
      {g && (
        <div data-testid="fc-guide" className="space-y-2">
          <div className="text-[11px] uppercase tracking-wider text-slate-500">{t('vi_fc_guide')}</div>
          {g.guides.map(x => (
            <div key={x.key} className="space-y-0.5 text-xs" data-testid={`fc-guide-${x.key}`}>
              <div className="text-slate-200 font-medium">{x.title}</div>
              <div className="text-slate-400">{x.cause}</div>
              <div className="text-slate-400">{x.impact}</div>
              <ol className="list-decimal pl-5 text-slate-300 space-y-0.5">{x.steps.map(s => <li key={s}>{s}</li>)}</ol>
            </div>
          ))}
          {(g.official_links || []).length > 0
            ? <div className="text-xs">{g.official_links!.map(l => <a key={l.id} href={l.url} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline mr-3">{l.title_tr || l.id}</a>)}</div>
            : g.vendor ? <div className="text-[11px] text-slate-500" data-testid="fc-no-links">{t('vi_fc_no_vendor_link', { vendor: g.vendor })}</div> : null}
        </div>
      )}
    </div>
  )
}
