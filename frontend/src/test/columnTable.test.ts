import { describe, expect, it } from 'vitest'
import { filterSortRows, type TableColumn } from '../components/ColumnTable'

type Row = { name: string; cpu: number | null }
const cols: TableColumn<Row>[] = [
  { id: 'name', label: 'VM', text: r => r.name },
  { id: 'cpu', label: 'vCPU', text: r => r.cpu == null ? '' : String(r.cpu), num: r => r.cpu },
]
const rows: Row[] = [
  { name: 'beta', cpu: 4 },
  { name: 'alpha', cpu: 1 },
  { name: 'gamma', cpu: null },
]

describe('filterSortRows', () => {
  it('arama tüm kolon metnine bakar', () => {
    expect(filterSortRows(rows, cols, 'alp', null).map(r => r.name)).toEqual(['alpha'])
    expect(filterSortRows(rows, cols, '4', null).map(r => r.name)).toEqual(['beta'])
  })
  it('sayı kolonu null’u sona atar', () => {
    expect(filterSortRows(rows, cols, '', { id: 'cpu', dir: 'asc' }).map(r => r.name)).toEqual(['alpha', 'beta', 'gamma'])
    expect(filterSortRows(rows, cols, '', { id: 'name', dir: 'desc' }).map(r => r.name)).toEqual(['gamma', 'beta', 'alpha'])
  })
})
