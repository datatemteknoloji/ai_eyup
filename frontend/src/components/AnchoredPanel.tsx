import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

type Pos = { left: number; top: number; maxHeight: number; openUp: boolean }

/**
 * Bir düğmeye (anchor) bağlı, `position: fixed` açılır panel (portal).
 * - Filtre çubuğunun `overflow`/ölçümünü etkilemez, kırpılmaz.
 * - Sağ kenara taşıyorsa sola doğru açılır (düğmenin sağ kenarına hizalanır); alta sığmazsa yukarı açılır.
 * - Esc ve dış tıklama kapatır; Esc'te odak anchor'a döner.
 */
export function AnchoredPanel({
  open,
  anchorRef,
  onClose,
  width = 288,
  label,
  children,
  className = '',
}: {
  open: boolean
  anchorRef: React.RefObject<HTMLElement | null>
  onClose: () => void
  width?: number
  label: string
  children: React.ReactNode
  className?: string
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<Pos | null>(null)

  const place = useCallback(() => {
    const a = anchorRef.current
    if (!a) return
    const r = a.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight
    const w = Math.min(width, vw - 16)
    let left = r.left
    if (left + w > vw - 8) left = r.right - w // sağa taşıyor → sola aç
    left = Math.max(8, Math.min(left, vw - w - 8))
    const below = vh - r.bottom - 12
    const above = r.top - 12
    const openUp = below < 220 && above > below
    const maxHeight = Math.max(160, Math.min(openUp ? above : below, 480))
    const top = openUp ? Math.max(8, r.top - 4 - Math.min(maxHeight, panelRef.current?.offsetHeight ?? maxHeight)) : r.bottom + 4
    setPos({ left, top, maxHeight, openUp })
  }, [anchorRef, width])

  useLayoutEffect(() => {
    if (!open) { setPos(null); return undefined }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open, place])

  // Yukarı açılırken gerçek yüksekliğe göre yeniden konumla
  useLayoutEffect(() => {
    if (open && pos?.openUp) place()
  }, [open, pos?.openUp, place, children])

  useEffect(() => {
    if (!open) return undefined
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (panelRef.current?.contains(t) || anchorRef.current?.contains(t)) return
      onClose()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
        anchorRef.current?.focus()
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose, anchorRef])

  if (!open) return null
  return createPortal(
    <div
      ref={panelRef}
      role="dialog"
      aria-label={label}
      style={{
        position: 'fixed',
        left: pos?.left ?? -9999,
        top: pos?.top ?? -9999,
        width: Math.min(width, window.innerWidth - 16),
        maxHeight: pos?.maxHeight ?? 480,
        visibility: pos ? 'visible' : 'hidden',
      }}
      className={`z-70 overflow-auto rounded-xl border border-white/[0.11] bg-[#0d1422] shadow-xl shadow-black/50 ${className}`}
    >
      {children}
    </div>,
    document.body,
  )
}
