import { useCallback, useState } from 'react'

export type HypervisorSelection = { ids: number[]; unassigned: boolean }

const EMPTY: HypervisorSelection = { ids: [], unassigned: false }
const keyOf = (platform: string) => `ainew.hv-filter.${platform}`

export function loadHypervisorSelection(platform: string): HypervisorSelection {
  try {
    const raw = window.localStorage.getItem(keyOf(platform))
    if (!raw) return EMPTY
    const d = JSON.parse(raw)
    const ids = Array.isArray(d?.ids)
      ? Array.from(new Set((d.ids as unknown[]).map(Number).filter((n) => Number.isInteger(n) && n > 0)))
      : []
    return { ids, unassigned: d?.unassigned === true }
  } catch {
    return EMPTY
  }
}

/** Ortam filtresi seçimi — platform başına localStorage'da saklanır. */
export function useHypervisorSelection(platform: 'linux' | 'windows') {
  const [sel, setSel] = useState<HypervisorSelection>(() => loadHypervisorSelection(platform))

  const setSelection = useCallback((ids: number[], unassigned: boolean) => {
    const next = { ids: Array.from(new Set(ids)).sort((a, b) => a - b), unassigned }
    setSel((prev) => {
      if (prev.unassigned === next.unassigned && prev.ids.length === next.ids.length && prev.ids.every((v, i) => v === next.ids[i])) {
        return prev
      }
      try {
        if (!next.ids.length && !next.unassigned) window.localStorage.removeItem(keyOf(platform))
        else window.localStorage.setItem(keyOf(platform), JSON.stringify(next))
      } catch { /* depolama kapalı olabilir */ }
      return next
    })
  }, [platform])

  /** Liste/summary/sekme sorguları için ortak parametreler. */
  const params = {
    hypervisor_ids: sel.ids.length ? sel.ids.join(',') : undefined,
    unassigned_hypervisor: sel.unassigned ? true : undefined,
  }

  return { ids: sel.ids, unassigned: sel.unassigned, setSelection, params }
}
