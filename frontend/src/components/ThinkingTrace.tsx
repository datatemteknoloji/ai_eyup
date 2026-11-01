import { useEffect, useRef } from 'react'
import { Brain } from 'lucide-react'
import { useT } from '../i18n/LocaleProvider'

/**
 * Adım 14: modelin akıl yürütmesi (cevap DEĞİL) — katlanır, canlı akar.
 * `live` (henüz cevap metni yok) iken açık; cevap başlayınca kullanıcı açmadıkça kapanır.
 */
export default function ThinkingTrace({ text, live }: { text: string; live: boolean }) {
  const t = useT()
  const boxRef = useRef<HTMLPreElement | null>(null)
  useEffect(() => {
    const el = boxRef.current
    if (el && live) el.scrollTop = el.scrollHeight
  }, [text, live])
  if (!text) return null
  return (
    <details
      className="mb-2 rounded-md border border-slate-700/60 bg-slate-900/40 text-xs text-slate-400"
      open={live}
      data-testid="thinking-trace"
    >
      <summary className="cursor-pointer select-none px-2 py-1 flex items-center gap-1.5 text-slate-400">
        <Brain size={12} strokeWidth={2} className={live ? 'animate-pulse' : ''} />
        <span>{t('chat_thinking_trace')}</span>
      </summary>
      <pre
        ref={boxRef}
        className="px-2 pb-2 max-h-40 overflow-y-auto whitespace-pre-wrap wrap-break-word font-sans text-[11px] leading-snug text-slate-500"
      >
        {text}
      </pre>
    </details>
  )
}
