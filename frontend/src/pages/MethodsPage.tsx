import React, { useMemo, useState } from 'react'
import { useLocale, useT } from '../i18n/LocaleProvider'
import { PageHeader } from '../components/aiops/ui'
import { Panel } from '../components/insights/insightsKit'
import { CLASS_STYLE, useMethodCatalog, type MethodClass } from '../components/insights/MethodBadge'

/** "Nasıl hesaplıyoruz?" — içerik tamamen yöntem kaydından (GET /api/v1/methods) üretilir; elle yazılmış kopya yoktur. */
export default function MethodsPage() {
  const t = useT()
  const { locale } = useLocale()
  const en = locale === 'en'
  const q = useMethodCatalog()
  const [cls, setCls] = useState<MethodClass | ''>('')
  const [text, setText] = useState('')
  const cat = q.data
  const rows = useMemo(() => {
    const n = text.trim().toLowerCase()
    return (cat?.methods || []).filter(m => {
      if (cls && m.cls !== cls) return false
      if (!n) return true
      return [m.id, m.method_tr, m.method_en, m.source_tr, m.source_en].join(' ').toLowerCase().includes(n)
    })
  }, [cat, cls, text])
  const areas = useMemo(() => {
    const g: Record<string, typeof rows> = {}
    rows.forEach(m => { (g[m.area] ||= []).push(m) })
    return Object.entries(g).sort(([a], [b]) => a.localeCompare(b))
  }, [rows])
  const lbl = (c: { label_tr: string; label_en: string }) => (en ? c.label_en : c.label_tr)

  return (
    <div className="space-y-5">
      <PageHeader title={t('method_page')} subtitle={t('method_page_sub')} />
      {q.isLoading && <div className="text-sm text-slate-400">{t('loading')}</div>}
      {q.error && <div className="text-sm text-red-300">{(q.error as Error).message}</div>}
      {cat && (
        <>
          <Panel title={t('method_classes_title')}>
            <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-slate-300">
              {cat.classes.map(c => (
                <div key={c.id} className="flex gap-2 items-start">
                  <span className={`text-[10px] leading-none px-1.5 py-[3px] rounded border font-medium whitespace-nowrap mt-0.5 ${CLASS_STYLE[c.id]}`}>{lbl(c)}</span>
                  <span>{en ? c.desc_en : c.desc_tr}</span>
                </div>
              ))}
            </div>
            <div className="px-4 pb-4 text-xs text-violet-300/80">{en ? cat.ai_note_en : cat.ai_note_tr}</div>
          </Panel>

          <div className="flex flex-wrap items-center gap-2">
            <select className="input-field text-sm" value={cls} onChange={e => setCls(e.target.value as MethodClass | '')}>
              <option value="">{t('vi_all')}</option>
              {cat.classes.map(c => <option key={c.id} value={c.id}>{lbl(c)}</option>)}
            </select>
            <input className="input-field text-sm w-64" placeholder={t('method_search')} value={text} onChange={e => setText(e.target.value)} />
            <span className="text-xs text-slate-500">{rows.length} / {cat.methods.length}</span>
          </div>

          {areas.map(([area, list]) => (
            <Panel key={area} title={t(`method_area_${area}` as any) === `method_area_${area}` ? area : t(`method_area_${area}` as any)}>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-white/[0.06]">
                      <th className="px-3 py-2">{t('method_col_class')}</th>
                      <th className="px-3 py-2">{t('method_col_what')}</th>
                      <th className="px-3 py-2">{t('method_lbl_method')}</th>
                      <th className="px-3 py-2">{t('method_lbl_source')}</th>
                      <th className="px-3 py-2">{t('method_lbl_limits')}</th>
                      <th className="px-3 py-2">{t('method_col_ai')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map(m => {
                      const c = cat.classes.find(x => x.id === m.cls)!
                      const formula = en ? m.formula_en : m.formula_tr
                      return (
                        <tr key={m.id} className="border-b border-white/[0.04] align-top" data-method-row={m.id}>
                          <td className="px-3 py-2"><span className={`text-[10px] leading-none px-1.5 py-[3px] rounded border font-medium whitespace-nowrap ${CLASS_STYLE[m.cls]}`}>{lbl(c)}</span></td>
                          <td className="px-3 py-2 font-mono text-[11px] text-slate-300 break-all">{m.id}</td>
                          <td className="px-3 py-2 text-xs text-slate-200 min-w-[16rem]">
                            {en ? m.method_en : m.method_tr}
                            {formula && (
                              <details className="mt-1">
                                <summary className="cursor-pointer text-blue-300 text-[11px]">{t('method_formula')}</summary>
                                <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px] text-slate-400 bg-black/30 rounded p-2">{formula}</pre>
                              </details>
                            )}
                          </td>
                          <td className="px-3 py-2 text-xs text-slate-400 min-w-[12rem]">{en ? m.source_en : m.source_tr}</td>
                          <td className="px-3 py-2 text-xs text-slate-400 min-w-[12rem]">{en ? m.limits_en : m.limits_tr}</td>
                          <td className="px-3 py-2 text-xs">{m.uses_ai ? <span className="text-violet-300">{t('method_ai_yes')}</span> : <span className="text-slate-500">{t('method_ai_no')}</span>}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </Panel>
          ))}
        </>
      )}
    </div>
  )
}
