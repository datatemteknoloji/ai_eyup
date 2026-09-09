import { useCallback, useMemo, useState } from 'react'
import { exportChatMessagesToPrintWindow, type PdfExportOptions } from '../utils/pdfExport'

export type ChatPdfMsg = {
  id: string | number
  role: string
  content: string
  created_at?: string
}

export type ChatPdfPair<T extends ChatPdfMsg = ChatPdfMsg> = {
  id: string
  messages: T[]
}

/** Soru + hemen ardından gelen cevabı bir çift olarak gruplar. */
export function pairChatMessages<T extends ChatPdfMsg>(messages: T[]): ChatPdfPair<T>[] {
  const pairs: ChatPdfPair<T>[] = []
  let i = 0
  while (i < messages.length) {
    const cur = messages[i]
    if (!cur) break
    const nxt = messages[i + 1]
    if (cur.role === 'user' && nxt?.role === 'assistant') {
      pairs.push({ id: `p-${cur.id}-${nxt.id}`, messages: [cur, nxt] })
      i += 2
      continue
    }
    pairs.push({ id: `p-${cur.id}`, messages: [cur] })
    i += 1
  }
  return pairs
}

export function useChatPdfSelect() {
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(() => new Set())

  const toggle = useCallback((id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const selectAll = useCallback((ids: string[]) => {
    setSelected(new Set(ids))
  }, [])

  const clear = useCallback(() => setSelected(new Set()), [])

  const enter = useCallback(() => {
    setSelectMode(true)
    setSelected(new Set())
  }, [])

  const exit = useCallback(() => {
    setSelectMode(false)
    setSelected(new Set())
  }, [])

  const reset = useCallback(() => {
    setSelectMode(false)
    setSelected(new Set())
  }, [])

  const selectedCount = selected.size

  const exportSelected = useCallback((
    pairs: ChatPdfPair[],
    options: PdfExportOptions,
  ) => {
    const msgs = pairs
      .filter(p => selected.has(p.id))
      .flatMap(p => p.messages)
    exportChatMessagesToPrintWindow(msgs, options)
  }, [selected])

  return useMemo(() => ({
    selectMode,
    selected,
    selectedCount,
    toggle,
    selectAll,
    clear,
    enter,
    exit,
    reset,
    exportSelected,
  }), [
    selectMode, selected, selectedCount, toggle, selectAll, clear,
    enter, exit, reset, exportSelected,
  ])
}
