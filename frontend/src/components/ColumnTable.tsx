import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown, Search } from 'lucide-react'

export interface TableColumn<T> {
  id: string
  label: string
  /** Arama ve metin sıralaması bu metne bakar. */
  text: (row: T) => string
  /** Varsa sayısal sıralama kullanılır. */
  num?: (row: T) => number | null | undefined
  render?: (row: T) => React.ReactNode
  /** false → başlık tıklanıp sıralanamaz (varsayılan: sıralanabilir). */
  sortable?: boolean
  /** Başlık tooltip'i (ör. eşik açıklaması). */
  hint?: string
  /** <th>/<td> için ek sınıf (genişlik, hizalama). */
  className?: string
}

export type SortState = { id: string; dir: 'asc' | 'desc' } | null

export function filterSortRows<T>(
  rows: T[],
  columns: TableColumn<T>[],
  query: string,
  sort: { id: string; dir: 'asc' | 'desc' } | null,
): T[] {
  const needle = query.trim().toLocaleLowerCase('tr')
  let list = rows
  if (needle) {
    list = list.filter(row => columns.some(c => (c.text(row) || '').toLocaleLowerCase('tr').includes(needle)))
  }
  if (!sort) return list
  const col = columns.find(c => c.id === sort.id)
  if (!col) return list
  const dir = sort.dir === 'asc' ? 1 : -1
  return [...list].sort((a, b) => {
    if (col.num) {
      const av = col.num(a)
      const bv = col.num(b)
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      return (av - bv) * dir
    }
    return (col.text(a) || '').localeCompare(col.text(b) || '', 'tr', { sensitivity: 'base' }) * dir
  })
}

/**
 * Ortak sıralanabilir/aranabilir tablo (proje geneli).
 * - Başlık tıklaması: artan → azalan → kapalı. Sayısal kolonda `num` kullanılır, boşlar hep sonda.
 * - `maxHeightClass` verilirse gövde kaydırılır ve başlık yapışkan kalır (uzun listeler sayfayı şişirmez).
 * - `bare` kartı/kenarlığı kaldırır (başka bir kartın içine gömmek için).
 */
export function ColumnTable<T>({
  rows, columns, rowKey, searchPlaceholder, empty, loading, error, testId, rowTestId,
  hideSearch, maxHeightClass, defaultSort, onRowClick, rowClass, toolbar, bare, countLabel, pageSize,
}: {
  rows: T[]
  columns: TableColumn<T>[]
  rowKey: (row: T) => string | number
  searchPlaceholder: string
  empty: string
  loading?: boolean
  error?: string | null
  testId?: string
  rowTestId?: string
  hideSearch?: boolean
  /** Ör. `max-h-72` — verilirse gövde kaydırılır. */
  maxHeightClass?: string
  defaultSort?: SortState
  onRowClick?: (row: T) => void
  rowClass?: (row: T) => string
  /** Arama kutusunun sağına yerleşen serbest alan (filtre çipleri, sayaç…). */
  toolbar?: React.ReactNode
  bare?: boolean
  /** Verilirse «görünen / toplam» sayacı için kullanılır: (shown, total) → metin. */
  countLabel?: (shown: number, total: number) => string
  /** Verilirse satırlar sayfalanır (büyük listeler); arama/sıralama değişince 1. sayfaya döner. */
  pageSize?: number
}) {
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SortState>(defaultSort ?? null)
  const [page, setPage] = useState(0)
  const view = useMemo(() => filterSortRows(rows, columns, query, sort), [rows, columns, query, sort])
  const pages = pageSize ? Math.max(1, Math.ceil(view.length / pageSize)) : 1
  const cur = Math.min(page, pages - 1)
  const shownRows = pageSize ? view.slice(cur * pageSize, cur * pageSize + pageSize) : view
  const toggle = (id: string) => setSort(prev => {
    setPage(0)
    if (!prev || prev.id !== id) return { id, dir: 'asc' }
    if (prev.dir === 'asc') return { id, dir: 'desc' }
    return null
  })
  const showBar = !hideSearch || toolbar || countLabel

  return (
    <div className={bare ? '' : 'bg-cyber-card rounded-xl border border-white/[0.06] overflow-hidden'} data-testid={testId}>
      {showBar && (
        <div className="px-3 py-2 border-b border-white/[0.06] flex flex-wrap items-center gap-2">
          {!hideSearch && (
            <label className="relative block max-w-sm flex-1 min-w-[160px]">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                data-testid={testId ? `${testId}-search` : 'column-table-search'}
                value={query}
                onChange={e => { setQuery(e.target.value); setPage(0) }}
                placeholder={searchPlaceholder}
                className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg pl-8 pr-3 py-1.5 text-xs text-white placeholder:text-slate-500 focus:outline-hidden focus:border-blue-500/50"
              />
            </label>
          )}
          {toolbar}
          {countLabel && (
            <span className="ml-auto text-[11px] text-slate-500" data-testid={testId ? `${testId}-count` : undefined}>
              {countLabel(view.length, rows.length)}
            </span>
          )}
        </div>
      )}
      {loading ? <p className="text-sm text-slate-500 p-4">…</p>
        : error ? <p className="text-sm text-red-300 p-4">{error}</p>
        : !view.length ? <p className="text-sm text-slate-500 p-4">{empty}</p>
        : (
          <div className={`overflow-x-auto ${maxHeightClass ? `${maxHeightClass} overflow-y-auto` : ''}`}>
            <table className="w-full text-left text-xs">
              <thead className={maxHeightClass ? 'sticky top-0 z-10 bg-cyber-card' : undefined}>
                <tr className="text-slate-400 border-b border-white/[0.06]">
                  {columns.map(c => {
                    const active = sort?.id === c.id
                    const Icon = !active ? ArrowUpDown : sort.dir === 'asc' ? ArrowUp : ArrowDown
                    const sortable = c.sortable !== false
                    return (
                      <th
                        key={c.id}
                        title={c.hint}
                        className={`px-3 py-2 font-medium ${c.className || ''}`}
                        aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                      >
                        {sortable ? (
                          <button
                            type="button"
                            data-testid={testId ? `${testId}-sort-${c.id}` : undefined}
                            onClick={() => toggle(c.id)}
                            className={`inline-flex items-center gap-1 hover:text-slate-200 ${active ? 'text-sky-300' : ''}`}
                          >
                            {c.label}
                            <Icon className={`w-3 h-3 ${active ? '' : 'opacity-40'}`} />
                          </button>
                        ) : c.label}
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {shownRows.map(row => (
                  <tr
                    key={rowKey(row)}
                    className={`border-b border-white/[0.04] text-slate-300 ${onRowClick ? 'cursor-pointer hover:bg-white/[0.03]' : ''} ${rowClass ? rowClass(row) : ''}`}
                    data-testid={rowTestId}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                  >
                    {columns.map(c => (
                      <td key={c.id} className={`px-3 py-1.5 ${c.className || ''}`}>{c.render ? c.render(row) : (c.text(row) || '—')}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      {pageSize && view.length > pageSize && (
        <div className="px-3 py-2 border-t border-white/[0.06] flex items-center justify-end gap-2 text-[11px] text-slate-500">
          <span data-testid={testId ? `${testId}-page` : undefined}>
            {cur * pageSize + 1}–{Math.min(view.length, cur * pageSize + pageSize)} / {view.length}
          </span>
          <button type="button" disabled={cur === 0} onClick={() => setPage(cur - 1)}
            data-testid={testId ? `${testId}-prev` : undefined}
            className="px-2 py-0.5 rounded-sm border border-white/[0.08] disabled:opacity-30 hover:text-slate-200">‹</button>
          <button type="button" disabled={cur >= pages - 1} onClick={() => setPage(cur + 1)}
            data-testid={testId ? `${testId}-next` : undefined}
            className="px-2 py-0.5 rounded-sm border border-white/[0.08] disabled:opacity-30 hover:text-slate-200">›</button>
        </div>
      )}
    </div>
  )
}
