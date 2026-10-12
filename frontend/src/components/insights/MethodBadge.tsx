import React, { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Info, Sparkles } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useLocale, useT } from '../../i18n/LocaleProvider'

/**
 * Yöntem şeffaflığı (Dilim T): rozet + (i). İçerik TEK kaynaktan gelir — backend `method_registry`
 * (GET /api/v1/methods). Kayıtsız id rozet göstermez; CI testi (`methodRegistry.test.ts`) kayıtsız id'yi yakalar.
 */

export type MethodClass = 'veri' | 'hesap' | 'tahmin' | 'kural' | 'eslestirme' | 'ai'

export type MethodEntry = {
  id: string
  cls: MethodClass
  area: string
  method_tr: string; method_en: string
  source_tr: string; source_en: string
  limits_tr: string; limits_en: string
  uses_ai: boolean
  formula_tr: string; formula_en: string
}

export type MethodCatalog = {
  classes: { id: MethodClass; label_tr: string; label_en: string; desc_tr: string; desc_en: string }[]
  ai_note_tr: string; ai_note_en: string
  general_knowledge_tr: string; general_knowledge_en: string
  methods: MethodEntry[]
  /** Eski kimlik → güncel kimlik (ör. upg:feed_stale → ref.feed.stale). */
  aliases?: Record<string, string>
}

export const CLASS_STYLE: Record<MethodClass, string> = {
  veri: 'text-sky-300 border-sky-500/30 bg-sky-500/10',
  hesap: 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10',
  tahmin: 'text-amber-200 border-amber-500/30 bg-amber-500/10',
  kural: 'text-slate-200 border-slate-400/30 bg-slate-400/10',
  eslestirme: 'text-cyan-300 border-cyan-500/30 bg-cyan-500/10',
  ai: 'text-violet-300 border-violet-500/40 bg-violet-500/10',
}

export function useMethodCatalog() {
  return useQuery<MethodCatalog>({
    queryKey: ['methods-catalog'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/methods`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    },
    staleTime: 60 * 60 * 1000,
  })
}

/** Tam kimlik, yoksa en uzun `önek*` deseni (backend `method_registry.resolve` ile aynı kural). */
export function resolveMethod(cat: MethodCatalog | undefined, id: string): MethodEntry | undefined {
  if (!cat || !id) return undefined
  id = cat.aliases?.[id] ?? id
  const exact = cat.methods.find(m => m.id === id)
  if (exact) return exact
  let best: MethodEntry | undefined
  for (const m of cat.methods) {
    if (m.id.endsWith('*') && id.startsWith(m.id.slice(0, -1)) && (!best || m.id.length > best.id.length)) best = m
  }
  return best
}

export function useMethod(id: string | undefined) {
  const q = useMethodCatalog()
  const { locale } = useLocale()
  const en = locale === 'en'
  return useMemo(() => {
    const cat = q.data
    const m = id ? resolveMethod(cat, id) : undefined
    const cls = m ? cat?.classes.find(c => c.id === m.cls) : undefined
    return {
      cat, m, en,
      classLabel: cls ? (en ? cls.label_en : cls.label_tr) : '',
      method: m ? (en ? m.method_en : m.method_tr) : '',
      source: m ? (en ? m.source_en : m.source_tr) : '',
      limits: m ? (en ? m.limits_en : m.limits_tr) : '',
      aiNote: cat ? (en ? cat.ai_note_en : cat.ai_note_tr) : '',
      generalNote: cat ? (en ? cat.general_knowledge_en : cat.general_knowledge_tr) : '',
    }
  }, [q.data, id, en])
}

function Popover({ anchor, onClose, children }: { anchor: HTMLElement | null; onClose: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  useLayoutEffect(() => {
    if (!anchor) return
    const r = anchor.getBoundingClientRect()
    const w = 340
    const left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left))
    const below = r.bottom + 6
    setPos({ top: below + 200 > window.innerHeight ? Math.max(8, r.top - 6 - 190) : below, left })
  }, [anchor])
  React.useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node) && !anchor?.contains(e.target as Node)) onClose()
    }
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('mousedown', h)
    document.addEventListener('keydown', k)
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k) }
  }, [anchor, onClose])
  if (!pos) return null
  return createPortal(
    <div ref={ref} style={{ top: pos.top, left: pos.left, width: 340 }}
      className="fixed z-[200] rounded-lg border border-white/[0.12] bg-cyber-card shadow-2xl p-3 text-left text-xs text-slate-300 space-y-1.5"
      onClick={e => e.stopPropagation()}>
      {children}
    </div>,
    document.body,
  )
}

/** Sınıf rozeti + (i). `at`: bu sayının/kartın veri zamanı (ISO string veya Date). */
export function MethodBadge({ id, at, computedAt, className = '' }: {
  id: string
  /** Verinin zamanı (envanter/senkron/ölçüm). */
  at?: string | Date | null
  /** Sonucun hesaplandığı an — veri zamanından farklıysa ayrıca gösterilir. */
  computedAt?: string | Date | null
  className?: string
}) {
  const t = useT()
  const { m, classLabel, method, source, limits, aiNote } = useMethod(id)
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const close = useCallback(() => setOpen(false), [])
  if (!m) return null
  const when = at ? new Date(at).toLocaleString() : ''
  const computed = computedAt ? new Date(computedAt).toLocaleString() : ''
  return (
    <span className={`inline-flex items-center gap-1 align-middle ${className}`} data-method-id={id}>
      <span className={`text-[10px] leading-none px-1.5 py-[3px] rounded border font-medium whitespace-nowrap ${CLASS_STYLE[m.cls]}`}>
        {classLabel}
      </span>
      <button type="button" ref={setAnchor} aria-label={t('method_info_btn')} title={t('method_info_btn')}
        onClick={e => { e.stopPropagation(); setOpen(o => !o) }}
        className="inline-flex items-center justify-center w-4 h-4 rounded-full text-slate-500 hover:text-blue-300 transition-colors">
        <Info size={12} />
      </button>
      {open && (
        <Popover anchor={anchor} onClose={close}>
          <div><span className="text-slate-500">{t('method_lbl_method')}: </span>{method}</div>
          <div><span className="text-slate-500">{t('method_lbl_source')}: </span>{source}</div>
          {when && <div><span className="text-slate-500">{t('method_lbl_data_time')}: </span>{when}</div>}
          {computed && <div><span className="text-slate-500">{t('method_lbl_computed_time')}: </span>{computed}</div>}
          <div><span className="text-slate-500">{t('method_lbl_limits')}: </span>{limits}</div>
          {m.cls === 'ai' && <div className="text-violet-300">{aiNote}</div>}
          <Link to="/methods" className="inline-block text-blue-400 hover:underline pt-0.5" onClick={close}>{t('method_how_link')}</Link>
        </Popover>
      )}
    </span>
  )
}

/**
 * AI üretimli metin bloğu: görsel olarak ayrı (etiket + farklı zemin). Backend sayıları bu kutuya KARIŞTIRILMAZ —
 * sayılar ayrı kartlarda/tablolarda, metin burada. `method` verilirse rozet + (i) de gösterilir.
 */
export function AiBlock({ children, method = 'ai.chat', title, className = '' }: {
  children: React.ReactNode; method?: string; title?: string; className?: string
}) {
  const t = useT()
  const { aiNote } = useMethod(method)
  return (
    <div className={`rounded-lg border border-violet-500/25 bg-violet-500/[0.06] ${className}`} data-ai-block>
      <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-b border-violet-500/15">
        <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-violet-300">
          <Sparkles size={12} />{title || t('method_ai_block')}
        </span>
        <MethodBadge id={method} />
      </div>
      <div className="px-3 py-2.5 text-sm text-slate-200">{children}</div>
      {aiNote && <div className="px-3 pb-2 text-[10px] text-violet-300/70">{aiNote}</div>}
    </div>
  )
}
