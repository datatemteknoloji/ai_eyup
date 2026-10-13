import React, { useEffect, useRef, useState } from 'react'
import { Info } from 'lucide-react'
import { useT } from '../../i18n/LocaleProvider'

/** (i) bilgi balonu — tıklayınca açılır, dışarı tıklayınca/Esc ile kapanır. (VirtCapacity'den taşındı; davranış aynı.) */
export function InfoDot({ text, label }: { text: string; label: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement | null>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])
  return (
    <span ref={ref} className="relative inline-flex align-middle ml-1.5" onClick={e => e.stopPropagation()}>
      <button type="button" aria-label={label} title={label} onClick={() => setOpen(o => !o)}
        className="text-slate-400 hover:text-blue-300"><Info size={14} /></button>
      {open && (
        <span role="tooltip" className="absolute left-0 top-5 z-30 w-72 rounded-lg border border-white/[0.12] bg-slate-900 p-3 text-[11px] leading-snug text-slate-200 shadow-xl font-normal normal-case tracking-normal">
          {text}
        </span>
      )}
    </span>
  )
}

/** Terim/alan yanında (i): metin `vi_hint_<k>` i18n anahtarından gelir (1–2 cümle). */
export function TermHint({ k }: { k: string }) {
  const t = useT()
  return <InfoDot label={t('info_btn')} text={t(`vi_hint_${k}` as any)} />
}
