import { AlertTriangle, CircleSlash, Info, Lightbulb } from 'lucide-react'
import { useT } from '../../i18n/LocaleProvider'
import type { TranslationKey } from '../../i18n/messages'

/**
 * Ortak rapor görseli — OpenShift ve Yönetici «Tüm Ortamlar» raporları (`view: "generic"`).
 * Şema: backend/app/services/generic_report.py. Veri yoksa bölüm «ölçülemedi» görünür; sayı uydurulmaz.
 */

export type GenericKpi = { label: string; value: string | number | null; sub?: string | null; tone?: string }
export type GenericSection = {
  title: string
  module?: string | null
  status: 'ok' | 'unmeasured' | 'excluded' | string
  kpis?: GenericKpi[]
  columns?: string[]
  rows?: unknown[][]
  note?: string | null
}
export type GenericReport = {
  view: 'generic'
  title: string
  kpis?: GenericKpi[]
  sections?: GenericSection[]
  recommendations?: string[]
  notes?: string[]
  excluded?: { module: string; reason: string }[]
  applicability?: Record<string, { included: boolean; reason?: string | null }>
}

export function isGenericReport(d: unknown): d is GenericReport {
  return !!d && typeof d === 'object' && (d as { view?: string }).view === 'generic'
}

const TONE_BOX: Record<string, string> = {
  ok: 'border-green-500/30 bg-green-500/5',
  warn: 'border-amber-500/30 bg-amber-500/5',
  crit: 'border-red-500/30 bg-red-500/5',
  info: 'border-blue-500/30 bg-blue-500/5',
  muted: 'border-slate-700/50 bg-slate-800/40',
}

// Backend modül etiketi (Türkçe teknik ad) → i18n anahtarı
const MODULE_KEYS: Record<string, TranslationKey> = {
  'Sanallaştırma': 'rpt_gen_mod_virt',
  OpenShift: 'rpt_gen_mod_openshift',
  Linux: 'rpt_gen_mod_linux',
  Windows: 'rpt_gen_mod_windows',
  Exadata: 'rpt_gen_mod_exadata',
}

const MODULE_ORDER = ['virt', 'openshift', 'linux', 'windows', 'exadata'] as const
const MODULE_KEY_BY_ID: Record<(typeof MODULE_ORDER)[number], TranslationKey> = {
  virt: 'rpt_gen_mod_virt', openshift: 'rpt_gen_mod_openshift', linux: 'rpt_gen_mod_linux',
  windows: 'rpt_gen_mod_windows', exadata: 'rpt_gen_mod_exadata',
}

function cellTone(v: unknown): string {
  if (typeof v !== 'string') return 'text-slate-300'
  const s = v.toLowerCase()
  // Backend durum sözcükleri Türkçe veya İngilizce gelir (rapor dili = arayüz dili)
  if (s.startsWith('ölçülemedi') || s.startsWith('not measured') || s === '—') return 'text-slate-500'
  if (s === 'kritik' || s.startsWith('başarısız') || s === 'sığmaz' || s.startsWith('eşik aşıldı') || s === 'silindi'
    || s === 'critical' || s.startsWith('failed') || s === 'does not fit' || s.startsWith('threshold exceeded') || s === 'deleted') return 'text-red-400 font-medium'
  if (s === 'dikkat' || s === 'güncelleme var' || s === 'çalışıyor'
    || s === 'attention' || s === 'update available' || s === 'running') return 'text-amber-400 font-medium'
  if (s === 'normal' || s === 'başarılı' || s === 'güncel' || s === 'sığar'
    || s === 'succeeded' || s === 'up to date' || s.startsWith('fits')) return 'text-green-400'
  return 'text-slate-300'
}

function ModuleBadge({ label }: { label: string }) {
  const t = useT()
  const key = MODULE_KEYS[label]
  return (
    <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-300 border border-blue-500/20">
      {key ? t(key) : label}
    </span>
  )
}

function Kpi({ k }: { k: GenericKpi }) {
  const box = TONE_BOX[k.tone || 'info'] || TONE_BOX.info
  const v = k.value === null || k.value === undefined || k.value === '' ? '—' : k.value
  return (
    <div className={`rounded-xl border p-4 ${box}`}>
      <div className="text-slate-400 text-xs">{k.label}</div>
      {/* text-slate-100: white temada koyu mürekkebe eşlenir; text-white şeffaf mavi kartta tema kuralına takılıyordu. */}
      <div className="mt-2 text-2xl font-bold text-slate-100 break-words" data-testid="kpi-value">{v}</div>
      {k.sub && <div className="text-slate-500 text-xs mt-1">{k.sub}</div>}
    </div>
  )
}

function Cell({ v }: { v: unknown }) {
  const t = useT()
  if (v === null || v === undefined || v === '') return <span className="text-slate-600">—</span>
  if (typeof v === 'boolean') return <span className={v ? 'text-slate-200' : 'text-slate-500'}>{v ? t('yes') : t('no')}</span>
  return <span className={cellTone(v)}>{String(v)}</span>
}

function Section({ s }: { s: GenericSection }) {
  const t = useT()
  const unmeasured = s.status === 'unmeasured'
  const cols = s.columns || []
  const rows = s.rows || []
  return (
    <section className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-4 space-y-3" data-testid="generic-section">
      <div className="flex items-center gap-2 flex-wrap">
        {s.module && <ModuleBadge label={s.module} />}
        <h3 className="text-slate-200 text-sm font-semibold">{s.title}</h3>
        {unmeasured && (
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-slate-700/60 text-slate-300 border border-slate-600/50 inline-flex items-center gap-1">
            <CircleSlash size={11} /> {t('rpt_gen_unmeasured')}
          </span>
        )}
      </div>
      {(s.kpis || []).length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {(s.kpis || []).map((k, i) => <Kpi key={i} k={k} />)}
        </div>
      )}
      {unmeasured && s.note && <p className="text-sm text-slate-400">{s.note}</p>}
      {!unmeasured && cols.length > 0 && (
        rows.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border border-slate-700/40">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-slate-800/60 text-slate-400">
                  {cols.map((c, i) => <th key={i} className="text-left px-3 py-2 font-medium whitespace-nowrap">{c}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, ri) => (
                  <tr key={ri} className="border-t border-slate-700/30 hover:bg-slate-700/20">
                    {cols.map((_c, ci) => <td key={ci} className="px-3 py-1.5 align-top"><Cell v={r[ci]} /></td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-slate-500">{t('rpt_gen_no_rows')}</p>
        )
      )}
      {!unmeasured && s.note && <p className="text-[11px] text-slate-500 flex gap-1.5"><Info size={12} className="shrink-0 mt-0.5" />{s.note}</p>}
    </section>
  )
}

export default function GenericReportView({ d }: { d: GenericReport }) {
  const t = useT()
  const kpis = d.kpis || []
  const sections = d.sections || []
  const excluded = d.excluded || []
  const recs = d.recommendations || []
  const notes = d.notes || []
  const cov = d.applicability
  return (
    <div className="space-y-5" data-testid="generic-report">
      {cov && (
        <div className="flex flex-wrap items-center gap-2 text-[11px]" data-testid="generic-coverage">
          <span className="text-slate-500">{t('rpt_gen_coverage')}:</span>
          {MODULE_ORDER.map((m) => {
            const a = cov[m]
            if (!a) return null
            return (
              <span
                key={m}
                title={a.reason || undefined}
                className={`px-2 py-0.5 rounded-full border ${a.included
                  ? 'bg-green-500/10 text-green-300 border-green-500/20'
                  : 'bg-slate-700/40 text-slate-500 border-slate-600/40 line-through'}`}
              >
                {t(MODULE_KEY_BY_ID[m])}
              </span>
            )
          })}
        </div>
      )}
      {kpis.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {kpis.map((k, i) => <Kpi key={i} k={k} />)}
        </div>
      )}
      {sections.map((s, i) => <Section key={i} s={s} />)}
      {excluded.length > 0 && (
        <section className="rounded-xl border border-slate-700/50 bg-slate-800/20 p-4" data-testid="generic-excluded">
          <h3 className="text-slate-300 text-sm font-semibold flex items-center gap-2 mb-1">
            <CircleSlash size={14} className="text-slate-500" /> {t('rpt_gen_excluded')}
          </h3>
          <p className="text-[11px] text-slate-500 mb-3">{t('rpt_gen_excluded_hint')}</p>
          <ul className="space-y-2">
            {excluded.map((e, i) => (
              <li key={i} className="flex gap-2 text-sm">
                <ModuleBadge label={e.module} />
                <span className="text-slate-400">{e.reason}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {recs.length > 0 && (
        <section className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
          <h3 className="text-amber-300 text-sm font-semibold flex items-center gap-2 mb-2">
            <Lightbulb size={14} /> {t('rpt_gen_recs')}
          </h3>
          <ol className="list-decimal list-inside space-y-1 text-sm text-slate-300">
            {recs.map((r, i) => <li key={i}>{r}</li>)}
          </ol>
        </section>
      )}
      {notes.length > 0 && (
        <section className="text-[11px] text-slate-500 space-y-1">
          <div className="flex items-center gap-1.5 text-slate-400"><AlertTriangle size={12} /> {t('rpt_gen_notes')}</div>
          {notes.map((n, i) => <p key={i}>{n}</p>)}
        </section>
      )}
    </div>
  )
}
