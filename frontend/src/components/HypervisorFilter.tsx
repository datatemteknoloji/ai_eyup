import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, Search } from 'lucide-react'
import {
  fetchHypervisorFacets,
  type HypervisorFacetEnv,
  type HypervisorFacetFilters,
} from '../api/servers'
import { useT } from '../i18n/LocaleProvider'
import { AnchoredPanel } from './AnchoredPanel'

/** Ortam sayısı bundan fazlaysa panelde arama kutusu gösterilir. */
const SEARCH_MIN_ENVS = 8

const isDemo = (e: HypervisorFacetEnv) => (e.status || '').toLowerCase() === 'fake'

function GroupCheckbox({ checked, indeterminate, onChange, label }: {
  checked: boolean
  indeterminate: boolean
  onChange: () => void
  label: string
}) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate
  }, [indeterminate])
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      onChange={onChange}
      aria-label={label}
      className="h-4 w-4 rounded-sm border-slate-600 bg-white/[0.07] text-blue-600 focus:ring-blue-500"
    />
  )
}

/**
 * Ortam (hypervisor) filtresi — tür başlıklı gruplar, ortam başına checkbox + adet.
 * Seçim `onChange(ids, includeUnassigned)` ile yukarı taşınır (localStorage: useHypervisorSelection).
 * Sayılar `facetFilters` (hypervisor filtreleri hariç liste filtreleri) ile sunucuda hesaplanır.
 */
export function HypervisorFilter({
  platform,
  selectedIds,
  includeUnassigned,
  onChange,
  facetFilters,
  className = '',
}: {
  platform: 'linux' | 'windows'
  selectedIds: number[]
  includeUnassigned: boolean
  onChange: (ids: number[], includeUnassigned: boolean) => void
  facetFilters?: HypervisorFacetFilters
  className?: string
}) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [term, setTerm] = useState('')
  const btnRef = useRef<HTMLButtonElement>(null)

  const { data: facets, isError, isFetching, isPlaceholderData } = useQuery({
    queryKey: ['hv-facets', platform, facetFilters ?? {}],
    queryFn: () => fetchHypervisorFacets(platform, facetFilters),
    refetchInterval: 60_000,
    placeholderData: (prev) => prev,
  })

  const allEnvs = useMemo(() => (facets?.groups ?? []).flatMap((g) => g.environments), [facets])
  const envById = useMemo(() => new Map(allEnvs.map((e) => [e.id, e])), [allEnvs])

  // Silinmiş ortam seçiliyse temizle (yalnızca gerçek, başarılı yanıttan sonra)
  useEffect(() => {
    if (!facets || isError || isPlaceholderData) return
    const valid = selectedIds.filter((id) => envById.has(id))
    if (valid.length !== selectedIds.length) onChange(valid, includeUnassigned)
  }, [facets, isError, isPlaceholderData, envById, selectedIds, includeUnassigned, onChange])

  const selected = useMemo(() => new Set(selectedIds), [selectedIds])
  const selCount = selectedIds.length + (includeUnassigned ? 1 : 0)
  const unassignedLabel = t('hv_env_unassigned')

  let label = t('hv_env_all')
  if (selCount === 1) {
    label = selectedIds.length === 1
      ? (envById.get(selectedIds[0])?.name ?? `#${selectedIds[0]}`)
      : t('hv_env_unassigned_short')
  } else if (selCount > 1) {
    label = t('hv_env_n', { n: selCount })
  }
  const fullTitle = selCount === 0
    ? t('hv_env_all')
    : [
        ...selectedIds.map((id) => envById.get(id)?.name ?? `#${id}`),
        ...(includeUnassigned ? [unassignedLabel] : []),
      ].join(', ')

  const showSearch = allEnvs.length > SEARCH_MIN_ENVS
  const q = term.trim().toLowerCase()
  const groups = useMemo(() => {
    return (facets?.groups ?? [])
      .map((g) => ({
        ...g,
        environments: q
          ? g.environments.filter((e) => e.name.toLowerCase().includes(q) || g.label.toLowerCase().includes(q))
          : g.environments,
      }))
      .filter((g) => g.environments.length > 0)
  }, [facets, q])

  const toggleEnv = (id: number) => {
    onChange(selected.has(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id], includeUnassigned)
  }
  const toggleGroup = (envs: HypervisorFacetEnv[]) => {
    const ids = envs.map((e) => e.id)
    const all = ids.every((id) => selected.has(id))
    onChange(
      all ? selectedIds.filter((id) => !ids.includes(id)) : Array.from(new Set([...selectedIds, ...ids])),
      includeUnassigned,
    )
  }

  const close = () => { setOpen(false); setTerm('') }

  return (
    <div className={`relative shrink-0 ${className}`}>
      <button
        ref={btnRef}
        type="button"
        onClick={() => (open ? close() : setOpen(true))}
        onKeyDown={(e) => { if (e.key === 'ArrowDown' && !open) { e.preventDefault(); setOpen(true) } }}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={fullTitle}
        data-testid="hv-filter-button"
        className={`flex min-w-[140px] max-w-[200px] items-center justify-between gap-2 whitespace-nowrap rounded-lg border bg-cyber-card px-3 py-1.5 text-left text-sm text-white focus:outline-hidden focus:ring-2 focus:ring-blue-500 ${
          selCount ? 'border-blue-500/50' : 'border-white/[0.06]'
        }`}
      >
        <span className="truncate">{label}</span>
        <ChevronDown size={14} className={`shrink-0 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      <AnchoredPanel open={open} anchorRef={btnRef} onClose={close} width={304} label={t('hv_env_all')}>
        {showSearch && (
          <div className="sticky top-0 border-b border-white/[0.06] bg-[#0d1422] p-2">
            <div className="relative">
              <Search size={13} className="pointer-events-none absolute left-2.5 top-2.5 text-slate-500" />
              <input
                autoFocus
                type="text"
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                placeholder={t('hv_env_search')}
                aria-label={t('hv_env_search')}
                className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] py-1.5 pl-8 pr-2 text-sm text-white placeholder-slate-500 focus:outline-hidden focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        )}

        <div className="py-1">
          {!facets && (
            <p className="px-3 py-3 text-xs text-slate-500">{isError ? t('hv_env_load_failed') : t('loading')}</p>
          )}
          {facets && groups.length === 0 && q && (
            <p className="px-3 py-3 text-xs text-slate-500">{t('hv_env_none_found')}</p>
          )}

          {groups.map((g) => {
            const ids = g.environments.map((e) => e.id)
            const nSel = ids.filter((id) => selected.has(id)).length
            const groupTotal = g.environments.reduce((a, e) => a + e.count, 0)
            return (
              <div key={g.type} role="group" aria-label={g.label}>
                <label
                  title={t('hv_env_group_toggle')}
                  className="flex cursor-pointer items-center gap-2 bg-white/[0.03] px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-300 hover:bg-white/[0.06]"
                >
                  <GroupCheckbox
                    checked={nSel === ids.length}
                    indeterminate={nSel > 0 && nSel < ids.length}
                    onChange={() => toggleGroup(g.environments)}
                    label={`${g.label}: ${t('hv_env_group_toggle')}`}
                  />
                  <span className="min-w-0 flex-1 truncate">{g.label}</span>
                  <span className="font-mono text-[11px] font-normal text-slate-500">{groupTotal}</span>
                </label>
                {g.environments.map((e) => (
                  <label
                    key={e.id}
                    title={e.name}
                    className={`flex cursor-pointer items-center gap-2 py-1.5 pl-7 pr-3 text-sm hover:bg-white/[0.04] ${
                      e.count === 0 ? 'text-slate-500' : 'text-slate-200'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(e.id)}
                      onChange={() => toggleEnv(e.id)}
                      className="h-4 w-4 rounded-sm border-slate-600 bg-white/[0.07] text-blue-600 focus:ring-blue-500"
                    />
                    <span className="min-w-0 flex-1 truncate">{e.name}</span>
                    {isDemo(e) && (
                      <span className="rounded-sm border border-amber-500/30 bg-amber-500/10 px-1 text-[10px] font-bold uppercase tracking-wide text-amber-300">
                        {t('hv_env_demo')}
                      </span>
                    )}
                    <span className="font-mono text-xs text-slate-500">{e.count}</span>
                  </label>
                ))}
              </div>
            )
          })}

          {facets && !q && (
            <label className="mt-1 flex cursor-pointer items-center gap-2 border-t border-white/[0.06] px-3 py-2 text-sm text-slate-200 hover:bg-white/[0.04]">
              <input
                type="checkbox"
                checked={includeUnassigned}
                onChange={() => onChange(selectedIds, !includeUnassigned)}
                className="h-4 w-4 rounded-sm border-slate-600 bg-white/[0.07] text-blue-600 focus:ring-blue-500"
              />
              <span className="min-w-0 flex-1 truncate" title={unassignedLabel}>{unassignedLabel}</span>
              <span className="font-mono text-xs text-slate-500">{facets.unassigned_count}</span>
            </label>
          )}
        </div>

        {selCount > 0 && (
          <div className="sticky bottom-0 flex items-center justify-between border-t border-white/[0.06] bg-[#0d1422] px-3 py-2">
            <span className="text-xs text-slate-400">{isFetching ? t('refreshing') : t('hv_env_n', { n: selCount })}</span>
            <button
              type="button"
              onClick={() => onChange([], false)}
              className="text-xs font-medium text-blue-400 underline hover:text-blue-300"
            >
              {t('hv_env_clear')}
            </button>
          </div>
        )}
      </AnchoredPanel>
    </div>
  )
}

export default HypervisorFilter
