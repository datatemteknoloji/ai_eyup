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
}

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

export function ColumnTable<T>({
  rows, columns, rowKey, searchPlaceholder, empty, loading, error, testId, rowTestId,
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
}) {
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<{ id: string; dir: 'asc' | 'desc' } | null>(null)
  const view = useMemo(() => filterSortRows(rows, columns, query, sort), [rows, columns, query, sort])
  const toggle = (id: string) => setSort(prev => {
    if (!prev || prev.id !== id) return { id, dir: 'asc' }
    if (prev.dir === 'asc') return { id, dir: 'desc' }
    return null
  })

  return (
    <div className="bg-cyber-card rounded-xl border border-white/[0.06] overflow-hidden" data-testid={testId}>
      <div className="px-3 py-2 border-b border-white/[0.06]">
        <label className="relative block max-w-sm">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            data-testid={testId ? `${testId}-search` : 'column-table-search'}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder={searchPlaceholder}
            className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg pl-8 pr-3 py-1.5 text-xs text-white placeholder:text-slate-500 focus:outline-hidden focus:border-blue-500/50"
          />
        </label>
      </div>
      {loading ? <p className="text-sm text-slate-500 p-4">…</p>
        : error ? <p className="text-sm text-red-300 p-4">{error}</p>
        : !view.length ? <p className="text-sm text-slate-500 p-4">{empty}</p>
        : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-slate-400 border-b border-white/[0.06]">
                  {columns.map(c => {
                    const active = sort?.id === c.id
                    const Icon = !active ? ArrowUpDown : sort.dir === 'asc' ? ArrowUp : ArrowDown
                    return (
                      <th key={c.id} className="px-3 py-2 font-medium" aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                        <button
                          type="button"
                          data-testid={testId ? `${testId}-sort-${c.id}` : undefined}
                          onClick={() => toggle(c.id)}
                          className={`inline-flex items-center gap-1 hover:text-slate-200 ${active ? 'text-sky-300' : ''}`}
                        >
                          {c.label}
                          <Icon className={`w-3 h-3 ${active ? '' : 'opacity-40'}`} />
                        </button>
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {view.map(row => (
                  <tr key={rowKey(row)} className="border-b border-white/[0.04] text-slate-300" data-testid={rowTestId}>
                    {columns.map(c => (
                      <td key={c.id} className="px-3 py-1.5">{c.render ? c.render(row) : (c.text(row) || '—')}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
    </div>
  )
}
