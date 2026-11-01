import { useLayoutEffect, useRef, useState } from 'react'

/**
 * Filtre çubuğu tek satırda kalsın: geniş yerleşim sığmıyorsa `compact=true` olur
 * (ikincil filtreler "Filtreler" panelinde toplanır). Alt satıra sarma / yatay kaydırma yok.
 *
 * `ref` çubuğun kendisine (flex-nowrap) bağlanır. Taşma, `scrollWidth > clientWidth` ile ölçülür;
 * ölçülen gereken genişlik saklanır, çubuk o genişliğe ulaşınca tekrar geniş yerleşime dönülür.
 * `resetKey` (ör. "Durum seçici göründü") değişince geniş yerleşim yeniden denenir.
 */
export function useSingleRowFit<T extends HTMLElement = HTMLDivElement>(resetKey: string) {
  const ref = useRef<T>(null)
  const [compact, setCompact] = useState(false)
  const needed = useRef(0)
  const prevKey = useRef(resetKey)

  if (prevKey.current !== resetKey) {
    prevKey.current = resetKey
    needed.current = 0
    if (compact) setCompact(false)
  }

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const check = () => {
      if (!compact) {
        if (el.scrollWidth > el.clientWidth + 1) {
          needed.current = el.scrollWidth
          setCompact(true)
        }
      } else if (needed.current > 0 && el.clientWidth >= needed.current) {
        setCompact(false)
      }
    }
    check()
    if (typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(check)
    ro.observe(el)
    return () => ro.disconnect()
  }, [compact, resetKey])

  return { ref, compact }
}
