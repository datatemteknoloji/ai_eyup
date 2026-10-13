import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { ListChecks, Search, ChevronLeft, ChevronRight } from 'lucide-react'
import { apiGet, qs, type Execution } from './api'
import {
  Card, ClientPicker, ErrorNote, ExecutionTable, fmtNumber, AutomicInfoButton, NoSystemNotice, RangePicker, SystemPicker,
  useSelectedSystem,
} from './ui'

type SearchResult = {
  total: number
  counts: Record<string, number>
  limit: number
  offset: number
  items: Execution[]
}

const PAGE = 50

const SORTS: [string, string][] = [
  ['end_desc', 'Bitiş (yeni → eski)'],
  ['end_asc', 'Bitiş (eski → yeni)'],
  ['duration_desc', 'Süre (uzun → kısa)'],
  ['duration_asc', 'Süre (kısa → uzun)'],
]

export default function AutomationExecutions() {
  const { systems, selected, setSystem } = useSelectedSystem()
  const [params, setParams] = useSearchParams()
  const get = (k: string, d = '') => params.get(k) ?? d
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === '') next.delete(k)
      else next.set(k, v)
    }
    if (!('offset' in patch)) next.delete('offset')
    setParams(next, { replace: true })
  }

  const range = get('range', '24h')
  const statusClass = get('status_class')
  const objectType = get('object_type')
  const sort = get('sort', 'end_desc')
  const offset = Number(get('offset', '0')) || 0
  const clients = get('clients').split(',').filter(Boolean).map(Number)
  const [objectName, setObjectName] = useState(get('object_name'))
  const [agent, setAgent] = useState(get('agent'))
  const [user, setUser] = useState(get('user'))
  const [folder, setFolder] = useState(get('folder'))

  useEffect(() => {
    setObjectName(get('object_name'))
    setAgent(get('agent'))
    setUser(get('user'))
    setFolder(get('folder'))
  }, [params.get('object_name'), params.get('agent'), params.get('user'), params.get('folder')]) // eslint-disable-line react-hooks/exhaustive-deps

  const q = useQuery({
    queryKey: ['automic-executions', selected?.id, params.toString()],
    queryFn: () => apiGet<SearchResult>(`/executions${qs({
      system_id: selected!.id, range, status_class: statusClass, object_type: objectType, sort,
      object_name: get('object_name'), agent: get('agent'), user: get('user'), folder: get('folder'),
      clients: clients.join(','),
      min_duration_sec: get('min_duration_sec'), limit: PAGE, offset,
    })}`),
    enabled: !!selected,
    placeholderData: keepPreviousData,
  })

  if (systems.isLoading) return <div className="p-6 text-sm text-slate-400">Yükleniyor…</div>
  if (!selected) return <NoSystemNotice />

  const d = q.data
  const applyText = () => set({
    object_name: objectName.trim() || null,
    agent: agent.trim() || null,
    user: user.trim() || null,
    folder: folder.trim() || null,
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300"><ListChecks size={18} /></div>
          <div>
            <h1 className="text-lg font-semibold text-white">Çalışmalar</h1>
            <p className="text-xs text-slate-500">Biten çalışmalar — modül veritabanından (salt okunur kopya)</p>
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <SystemPicker systems={systems.data ?? []} value={selected.id} onChange={setSystem} />
          <AutomicInfoButton systemId={selected.id} />
          <RangePicker value={range} onChange={v => set({ range: v })} />
        </div>
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
            <input value={objectName} onChange={e => setObjectName(e.target.value)} onKeyDown={e => e.key === 'Enter' && applyText()}
              placeholder="Nesne adı (* joker)" className="w-56 rounded-lg border border-slate-600 bg-slate-800 py-1.5 pl-8 pr-3 text-sm text-white placeholder-slate-500" />
          </div>
          <input value={agent} onChange={e => setAgent(e.target.value)} onKeyDown={e => e.key === 'Enter' && applyText()}
            placeholder="Agent" className="w-32 rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white placeholder-slate-500" />
          <input value={user} onChange={e => setUser(e.target.value)} onKeyDown={e => e.key === 'Enter' && applyText()}
            placeholder="Kullanıcı" className="w-32 rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white placeholder-slate-500" />
          <input value={folder} onChange={e => setFolder(e.target.value)} onKeyDown={e => e.key === 'Enter' && applyText()}
            placeholder="Klasör" className="w-32 rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white placeholder-slate-500" />
          <select value={statusClass} onChange={e => set({ status_class: e.target.value })} style={{ colorScheme: 'dark' }}
            className="rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white">
            <option value="">Tüm durumlar</option>
            <option value="failed">Hatalı</option>
            <option value="cancelled">İptal</option>
            <option value="ok">Başarılı</option>
          </select>
          <select value={objectType} onChange={e => set({ object_type: e.target.value })} style={{ colorScheme: 'dark' }}
            className="rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white">
            <option value="">Tüm tipler</option>
            {['JOBS', 'JOBP', 'JSCH', 'EVNT', 'SCRI', 'JOBF', 'CALL'].map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <select value={sort} onChange={e => set({ sort: e.target.value })} style={{ colorScheme: 'dark' }}
            className="rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white">
            {SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <button type="button" onClick={applyText} className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500">Uygula</button>
          <div className="w-full pt-1">
            <ClientPicker clients={selected.clients} value={clients} onChange={v => set({ clients: v.join(',') })} />
          </div>
        </div>
      </Card>

      {q.error ? <ErrorNote error={q.error} /> : null}

      <Card
        title={d ? (
          <span className="flex flex-wrap items-center gap-3 text-xs font-normal text-slate-400">
            <span><strong className="text-white">{fmtNumber(d.total)}</strong> kayıt</span>
            <span className="text-green-300">başarılı {fmtNumber(d.counts.ok ?? 0)}</span>
            <span className="text-red-300">hatalı {fmtNumber(d.counts.failed ?? 0)}</span>
            <span className="text-amber-300">iptal {fmtNumber(d.counts.cancelled ?? 0)}</span>
          </span>
        ) : 'Yükleniyor…'}
        actions={d && d.total > PAGE ? (
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <button type="button" disabled={offset === 0} onClick={() => set({ offset: String(Math.max(0, offset - PAGE)) })}
              className="rounded border border-slate-700 p-1 disabled:opacity-40"><ChevronLeft size={14} /></button>
            <span>{offset + 1}–{Math.min(offset + PAGE, d.total)} / {fmtNumber(d.total)}</span>
            <button type="button" disabled={offset + PAGE >= d.total} onClick={() => set({ offset: String(offset + PAGE) })}
              className="rounded border border-slate-700 p-1 disabled:opacity-40"><ChevronRight size={14} /></button>
          </div>
        ) : null}
      >
        <div className={q.isFetching ? 'opacity-60 transition-opacity' : ''}>
          <ExecutionTable
            systemId={selected.id}
            rows={d?.items ?? []}
            showClient={selected.clients.length > 1}
            sort={sort}
            onSort={v => set({ sort: v })}
          />
        </div>
      </Card>
    </div>
  )
}
