import React, { useState } from 'react'
import { useLocale, useT } from '../../i18n/LocaleProvider'
import { GhostButton, NEON } from '../aiops/ui'
import { apiSend, useInsights } from './insightsKit'
import { AiBlock } from './MethodBadge'
import { TermHint } from './InfoDot'

/** AI yorumu yalnız Yapılandırma (health) ve Donanım (hardware) bulgularında sunulur. */
export const AI_CATEGORIES = ['health', 'hardware']

type Comment = {
  id: number; version: number; model: string | null; generated_at: string | null; stale: boolean
  confidence: { level: 'high' | 'medium' | 'low'; reasons: string[] }
  content: { ozet: string; olay_gorunumu: string; etki: string; oncelik: string; gozlenen: string[]; genel_bilgi: string[]; diger_iyilestirmeler?: string[]; bilinmeyenler: string[] }
  /** Yorum OLAY başına üretilir; olayın tüm üye bulgularında aynı görünür. */
  event?: { key: string; family: string | null; member_count: number | null; member_ids: number[]; representative_id: number | null }
  feedback: { mine: boolean | null; helpful: number; not_helpful: number }
}
type State = { supported: boolean; available: boolean; reason?: string; comment: Comment | null }

const CONF_TONE: Record<string, string> = { high: 'text-emerald-300 border-emerald-500/30', medium: 'text-amber-300 border-amber-500/30', low: 'text-red-300 border-red-500/30' }

function Section({ title, children, testid }: { title: string; children: React.ReactNode; testid?: string }) {
  return (
    <div data-testid={testid}>
      <div className="text-[11px] uppercase tracking-wider text-slate-500">{title}</div>
      <div className="text-xs text-slate-200 leading-relaxed">{children}</div>
    </div>
  )
}

function Bullets({ items }: { items: string[] }) {
  return <ul className="list-disc pl-5 space-y-0.5">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
}

/** Saklı yorumu gösterir (üretim/yeniden üretim/geri bildirim üst bileşenden). Veri-dışı "genel bilgi" ayrı kutuda. */
export function AiCommentView({ c, busy, onRegen, onFeedback }: {
  c: Comment; busy: boolean; onRegen: () => void; onFeedback: (helpful: boolean) => void
}) {
  const t = useT()
  const k = c.content
  const conf = c.confidence
  return (
    <AiBlock method="ai.finding.comment" title={t('vi_ai_label')}>
      <div className="space-y-3" data-testid="ai-comment">
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
          <span className={`inline-flex items-center rounded border px-1.5 py-0.5 ${CONF_TONE[conf.level] || ''}`} data-testid={`ai-conf-${conf.level}`}>
            {t('vi_ai_conf')}: {t(`vi_ai_conf_${conf.level}` as any)}<TermHint k="ai_conf" />
          </span>
          {conf.reasons.length > 0 && <span data-testid="ai-conf-reasons">({conf.reasons.map(r => t(`vi_ai_cr_${r}` as any)).join('; ')})</span>}
          <span data-testid="ai-generated">{t('vi_ai_generated', { at: c.generated_at ? new Date(c.generated_at).toLocaleString() : '—', model: c.model || '—', v: c.version })}</span>
        </div>
        {c.stale && (
          <div className="flex flex-wrap items-center gap-2 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-200" data-testid="ai-stale">
            <span className="inline-flex items-center">{t('vi_ai_stale')}<TermHint k="ai_stale" /></span>
            <GhostButton accent={NEON.orange} onClick={onRegen}>{t('vi_ai_regen')}</GhostButton>
          </div>
        )}
        {(c.event?.member_count ?? 0) > 1 && (
          <div className="text-[11px] text-slate-400 inline-flex items-center" data-testid="ai-event-note">
            {t('vi_ai_event_note', { n: c.event!.member_count ?? 0 })}<TermHint k="ai_event" />
          </div>
        )}
        <Section title={t('vi_ai_sec_summary')} testid="ai-sec-summary">{k.ozet}</Section>
        <Section title={t('vi_ai_sec_incident')}>{k.olay_gorunumu}</Section>
        <Section title={t('vi_ai_sec_impact')}>{k.etki}</Section>
        <Section title={t('vi_ai_sec_priority')}>{k.oncelik}</Section>
        {k.gozlenen.length > 0 && <Section title={t('vi_ai_sec_observed')} testid="ai-sec-observed"><Bullets items={k.gozlenen} /></Section>}
        {k.genel_bilgi.length > 0 && (
          <div className="rounded border border-dashed border-slate-500/40 bg-black/20 p-2" data-testid="ai-sec-general">
            <div className="text-[11px] uppercase tracking-wider text-slate-500 inline-flex items-center">{t('vi_ai_sec_general')}<TermHint k="ai_general" /></div>
            <div className="text-xs text-slate-300 leading-relaxed"><Bullets items={k.genel_bilgi} /></div>
          </div>
        )}
        {(k.diger_iyilestirmeler || []).length > 0 && (
          <div className="rounded border border-white/[0.08] bg-black/10 p-2" data-testid="ai-sec-other">
            <div className="text-[11px] uppercase tracking-wider text-slate-500 inline-flex items-center">{t('vi_ai_sec_other')}<TermHint k="ai_other" /></div>
            <div className="text-xs text-slate-300 leading-relaxed"><Bullets items={k.diger_iyilestirmeler!} /></div>
          </div>
        )}
        {k.bilinmeyenler.length > 0 && <Section title={t('vi_ai_sec_unknown')} testid="ai-sec-unknown"><Bullets items={k.bilinmeyenler} /></Section>}
        <div className="flex flex-wrap items-center gap-2 border-t border-violet-500/15 pt-2 text-[11px] text-slate-400" data-testid="ai-feedback">
          <span>{t('vi_ai_fb_q')}</span>
          <button type="button" data-testid="ai-fb-yes" aria-pressed={c.feedback.mine === true} onClick={() => onFeedback(true)}
            className={`rounded border px-2 py-0.5 ${c.feedback.mine === true ? 'border-emerald-500/60 bg-emerald-600/20 text-emerald-200' : 'border-white/[0.1] hover:text-slate-200'}`}>{t('vi_ai_fb_yes')}</button>
          <button type="button" data-testid="ai-fb-no" aria-pressed={c.feedback.mine === false} onClick={() => onFeedback(false)}
            className={`rounded border px-2 py-0.5 ${c.feedback.mine === false ? 'border-red-500/60 bg-red-600/20 text-red-200' : 'border-white/[0.1] hover:text-slate-200'}`}>{t('vi_ai_fb_no')}</button>
          <span className="text-slate-500" data-testid="ai-fb-counts">{t('vi_ai_fb_counts', { up: c.feedback.helpful, down: c.feedback.not_helpful })}</span>
          {!c.stale && <GhostButton onClick={onRegen}>{busy ? t('vi_ai_generating') : t('vi_ai_regen')}</GhostButton>}
        </div>
      </div>
    </AiBlock>
  )
}

/** Bulgu satırı açıldığında: kayıtlı yorumu getirir (ÜRETMEZ); üretim yalnız düğmeyle. */
export default function FindingAiComment({ f }: { f: { id: number; category: string; result: string } }) {
  const t = useT()
  const { locale } = useLocale()
  const eligible = AI_CATEGORIES.includes(f.category) && f.result === 'fail'
  const q = useInsights<State>('virt-insights', `/findings/${f.id}/ai-comment`, { enabled: eligible })
  const [override, setOverride] = useState<State | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  if (!eligible) return null
  const st = override || q.data
  if (!st || st.supported === false) return null
  const gen = async () => {
    setBusy(true); setErr('')
    try {
      setOverride(await apiSend<State>('virt-insights', `/findings/${f.id}/ai-comment`, 'POST', undefined, locale))
    } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }
  const fb = async (helpful: boolean) => {
    if (!st.comment) return
    try {
      const r = await apiSend<any>('virt-insights', `/findings/${f.id}/ai-comment/feedback`, 'POST', { comment_id: st.comment.id, helpful })
      setOverride({ ...st, comment: { ...st.comment, feedback: { mine: r.mine, helpful: r.helpful, not_helpful: r.not_helpful } } })
    } catch (e: any) { setErr(e.message) }
  }
  return (
    <div className="space-y-2" data-testid="finding-ai">
      {!st.available && <div className="text-[11px] text-slate-500" data-testid="ai-unavailable">{t('vi_ai_tables_missing')}</div>}
      {st.available && !st.comment && (
        <div className="flex flex-wrap items-center gap-3">
          <GhostButton accent={NEON.blue} onClick={() => { if (!busy) void gen() }}>{busy ? t('vi_ai_generating') : t('vi_ai_btn')}</GhostButton>
          <span className="text-[11px] text-slate-500">{t('vi_ai_btn_hint')}</span>
        </div>
      )}
      {st.comment && <AiCommentView c={st.comment} busy={busy} onRegen={() => { if (!busy) void gen() }} onFeedback={fb} />}
      {err && <div className="text-xs text-red-300" data-testid="ai-error">{err}</div>}
    </div>
  )
}
