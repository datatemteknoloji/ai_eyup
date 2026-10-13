import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { PlayCircle, RefreshCw, Search } from 'lucide-react'
import { apiGet, qs } from './api'
import {
  Card, ErrorNote, ExecLink, fmtAgo, fmtDateTime, fmtDuration, fmtNumber, KpiTile, NoSystemNotice, ObjectLink,
  AutomicInfoButton, SortDir, SortTh, sortBy, SystemPicker, toggleSort, useSelectedSystem,
} from './ui'

type ActiveRow = {
  client: number
  run_id: number
  parent_run_id: number | null
  object_name: string
  object_type: string | null
  status_code: number | null
  activation_time: string | null
  start_time: string | null
  agent: string | null
  running_sec: number | null
  p95_duration_sec: number | null
  over_p95: boolean
  user?: string | null
  queue?: string | null
  folder?: string | null
  ert_sec?: number | null
  ert_end_time?: string | null
  over_ert?: boolean
  signals?: string[]
}

const SIGNAL_LABEL: Record<string, string> = {
  TCP_EXCEEDED: 'TCP aşıldı',
  MRT_EXCEEDED: 'MRT aşıldı',
  SRT_NOT_REACHED: 'SRT altında',
}

type ActiveResult = {
  ok: boolean
  total: number
  snapshot_at: string | null
  items: ActiveRow[]
  over_p95: ActiveRow[]
}

const SORT_GETTERS: Record<string, (r: ActiveRow) => string | number | null | undefined> = {
  object_name: r => r.object_name,
  object_type: r => r.object_type,
  status_code: r => r.status_code,
  start_time: r => r.start_time,
  running_sec: r => r.running_sec,
  p95: r => r.p95_duration_sec,
  ert: r => r.ert_sec,
  user: r => r.user,
  queue: r => r.queue,
  agent: r => r.agent,
  client: r => r.client,
  run_id: r => r.run_id,
}

export default function AutomationActive() {
  const { systems, selected, setSystem } = useSelectedSystem()
  const [onlyOver, setOnlyOver] = useState(false)
  const [filter, setFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [agentFilter, setAgentFilter] = useState('')
  const [sortCol, setSortCol] = useState('running_sec')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const q = useQuery({
    queryKey: ['automic-active', selected?.id],
    queryFn: () => apiGet<ActiveResult>(`/active${qs({ system_id: selected!.id, limit: 500 })}`),
    enabled: !!selected,
    refetchInterval: 60_000,
  })

  const types = useMemo(() => {
    const s = new Set((q.data?.items ?? []).map(r => r.object_type).filter(Boolean) as string[])
    return [...s].sort()
  }, [q.data])

  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase()
    const af = agentFilter.trim().toLowerCase()
    const base = (onlyOver ? q.data?.over_p95 : q.data?.items ?? []) ?? []
    const filtered = base.filter(r => {
      if (typeFilter && (r.object_type || '') !== typeFilter) return false
      if (af && !(r.agent ?? '').toLowerCase().includes(af)) return false
      if (!f) return true
      const hay = [
        r.object_name, r.agent, r.user, r.queue, r.folder,
        String(r.run_id), String(r.client), String(r.status_code ?? ''),
      ].join(' ').toLowerCase()
      return hay.includes(f)
    })
    return sortBy(filtered, sortCol, sortDir, SORT_GETTERS)
  }, [q.data, onlyOver, filter, typeFilter, agentFilter, sortCol, sortDir])

  if (systems.isLoading) return <div className="p-6 text-sm text-slate-400">Yükleniyor…</div>
  if (!selected) return <NoSystemNotice />

  const d = q.data
  const onSort = (col: string) => {
    const n = toggleSort(sortCol, sortDir, col)
    setSortCol(n.col)
    setSortDir(n.dir)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300"><PlayCircle size={18} /></div>
          <div>
            <h1 className="text-lg font-semibold text-white">Aktif İşler</h1>
            <p className="text-xs text-slate-500">
              Anlık görüntü {d?.snapshot_at ? `${fmtDateTime(d.snapshot_at, true)} (${fmtAgo(d.snapshot_at)})` : '—'} · kaynak gecikmesi kadar geride olabilir
            </p>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <SystemPicker systems={systems.data ?? []} value={selected.id} onChange={setSystem} />
          <AutomicInfoButton systemId={selected.id} />
          <button type="button" onClick={() => q.refetch()} className="rounded-lg border border-slate-700 p-1.5 text-slate-400 hover:text-white" title="Yenile">
            <RefreshCw size={14} className={q.isFetching ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {q.error ? <ErrorNote error={q.error} /> : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiTile label="Aktif çalışma" value={fmtNumber(d?.total)} />
        <KpiTile label="p95 süresini aşan" value={fmtNumber(d?.over_p95.length)} tone={d?.over_p95.length ? 'warning' : undefined} />
        <KpiTile label="ERT'yi aşan (AE tahmini)" value={fmtNumber((d?.items ?? []).filter(i => i.over_ert).length)}
          tone={(d?.items ?? []).some(i => i.over_ert) ? 'warning' : undefined} />
        <KpiTile label="Gösterilen" value={fmtNumber(rows.length)} />
      </div>

      <Card
        title="Çalışan işler"
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
              <input value={filter} onChange={e => setFilter(e.target.value)}
                placeholder="Nesne, kullanıcı, kuyruk, RunID…"
                className="w-52 rounded-lg border border-slate-600 bg-slate-800 py-1 pl-7 pr-2 text-xs text-white placeholder-slate-500" />
            </div>
            <input value={agentFilter} onChange={e => setAgentFilter(e.target.value)} placeholder="Agent"
              className="w-28 rounded-lg border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-white placeholder-slate-500" />
            <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)} style={{ colorScheme: 'dark' }}
              className="rounded-lg border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-white">
              <option value="">Tüm tipler</option>
              {types.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <label className="flex items-center gap-1.5 text-xs text-slate-400">
              <input type="checkbox" checked={onlyOver} onChange={e => setOnlyOver(e.target.checked)} /> yalnız p95 üstü
            </label>
          </div>
        )}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-slate-700/60 text-slate-400">
              <tr>
                <SortTh label="Nesne" col="object_name" active={sortCol} dir={sortDir} onSort={onSort} />
                <SortTh label="Tip" col="object_type" active={sortCol} dir={sortDir} onSort={onSort} />
                <SortTh label="Durum" col="status_code" active={sortCol} dir={sortDir} onSort={onSort} />
                <SortTh label="Başlangıç" col="start_time" active={sortCol} dir={sortDir} onSort={onSort} />
                <SortTh label="Çalışma süresi" col="running_sec" active={sortCol} dir={sortDir} onSort={onSort} />
                <SortTh label="p95" col="p95" active={sortCol} dir={sortDir} onSort={onSort} />
                <SortTh label="ERT · tahmini bitiş" col="ert" active={sortCol} dir={sortDir} onSort={onSort}
                  title="AE'nin kendi tahmini (EH_Ert / EH_ERTEnd)" />
                <th className="px-2 py-2 font-medium" title="EH_Signal bitmask">Sinyal</th>
                <SortTh label="Kullanıcı" col="user" active={sortCol} dir={sortDir} onSort={onSort} />
                <SortTh label="Kuyruk" col="queue" active={sortCol} dir={sortDir} onSort={onSort} />
                <SortTh label="Agent" col="agent" active={sortCol} dir={sortDir} onSort={onSort} />
                <SortTh label="Client" col="client" active={sortCol} dir={sortDir} onSort={onSort} />
                <SortTh label="RunID" col="run_id" active={sortCol} dir={sortDir} onSort={onSort} />
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={`${r.client}-${r.run_id}`} className={`border-b border-white/[0.04] ${r.over_p95 ? 'bg-amber-500/[0.06]' : ''}`}>
                  <td className="px-2 py-1.5"><ObjectLink systemId={selected.id} name={r.object_name} /></td>
                  <td className="px-2 py-1.5 text-slate-400">{r.object_type ?? '—'}</td>
                  <td className="px-2 py-1.5 font-mono text-slate-300">{r.status_code ?? '—'}</td>
                  <td className="px-2 py-1.5 whitespace-nowrap text-slate-400">{fmtDateTime(r.start_time)}</td>
                  <td className={`px-2 py-1.5 whitespace-nowrap ${r.over_p95 ? 'text-amber-300 font-medium' : 'text-slate-200'}`}>{fmtDuration(r.running_sec)}</td>
                  <td className="px-2 py-1.5 whitespace-nowrap text-slate-400">{fmtDuration(r.p95_duration_sec)}</td>
                  <td className={`px-2 py-1.5 whitespace-nowrap ${r.over_ert ? 'text-amber-300' : 'text-slate-400'}`}>
                    {r.ert_sec ? `${fmtDuration(r.ert_sec)}${r.ert_end_time ? ` · ${fmtDateTime(r.ert_end_time)}` : ''}` : '—'}
                  </td>
                  <td className="px-2 py-1.5 text-slate-400">
                    {r.signals?.length ? r.signals.map(s => SIGNAL_LABEL[s] ?? s).join(', ') : '—'}
                  </td>
                  <td className="px-2 py-1.5 text-slate-400">{r.user ?? '—'}</td>
                  <td className="px-2 py-1.5 text-slate-400">{r.queue ?? '—'}</td>
                  <td className="px-2 py-1.5 text-slate-400">{r.agent ?? '—'}</td>
                  <td className="px-2 py-1.5 font-mono text-slate-400">{r.client}</td>
                  <td className="px-2 py-1.5 font-mono text-slate-400">
                    {r.run_id}
                    {r.parent_run_id ? <> · üst <ExecLink systemId={selected.id} e={{ client: r.client, run_id: r.parent_run_id }} /></> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length && <p className="py-6 text-center text-xs text-slate-500">Kayıt yok</p>}
        </div>
      </Card>
    </div>
  )
}
