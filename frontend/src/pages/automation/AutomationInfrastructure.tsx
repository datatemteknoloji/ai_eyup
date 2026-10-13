import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Boxes, Globe, Search } from 'lucide-react'
import {
  agentPath, apiGet, engineServerPath, qs,
  type AwiServer, type EngineServer, type InfraAgentListItem, type InfraAgentsResponse, type InfraAwiResponse, type InfraEnginesResponse,
} from './api'
import {
  AutomicInfoButton, Card, EmptyNote, ErrorNote, fmtAgo, fmtDateTime, fmtNumber, InfraStatusBadge, NoSystemNotice,
  NoticeBox, SortDir, SortTh, sortBy, SystemPicker, toggleSort, useSelectedSystem,
} from './ui'

const STATUS_OPTIONS: [string, string][] = [
  ['', 'Tüm durumlar'], ['connected', 'bağlı'], ['disconnected', 'kopuk'], ['unknown', 'bilinmiyor'], ['missing', 'durdu'],
]

const AGENT_SORT: Record<string, (r: InfraAgentListItem) => string | number | null | undefined> = {
  status: r => ({ disconnected: 0, missing: 1, unknown: 2, connected: 3 }[r.status] ?? 9),
  name: r => r.name,
  hostname: r => r.hostname,
  ip: r => r.ip,
  platform: r => `${r.platform ?? ''} ${r.os ?? ''}`,
  groups: r => (r.groups ?? []).join(', '),
  last_life_sign: r => r.last_life_sign ?? r.missing_since,
  runs_24h: r => r.runs_24h,
  failed_24h: r => r.failed_24h,
}

function agentMatchesSearch(ag: InfraAgentListItem, q: string): boolean {
  if (!q) return true
  const hay = [
    ag.name,
    ag.hostname ?? '',
    ag.ip ?? '',
    ...(ag.groups ?? []),
  ].join(' ').toLowerCase()
  return hay.includes(q)
}

export default function AutomationInfrastructure() {
  const { systems, selected, setSystem } = useSelectedSystem()
  const [params, setParams] = useSearchParams()
  const get = (k: string, d = '') => params.get(k) ?? d
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === '') next.delete(k)
      else next.set(k, v)
    }
    setParams(next, { replace: true })
  }

  const status = get('status')
  const platform = get('platform')
  const team = get('team')
  const group = get('group')
  const missingHostname = get('missing_hostname') === '1'
  const [search, setSearch] = useState(get('q'))
  const [sortCol, setSortCol] = useState(get('asort', 'status'))
  const [sortDir, setSortDir] = useState<SortDir>((get('adir', 'asc') as SortDir) || 'asc')

  const engines = useQuery({
    queryKey: ['automic-infra-engines', selected?.id],
    queryFn: () => apiGet<InfraEnginesResponse>(`/infrastructure/engines${qs({ system_id: selected!.id })}`),
    enabled: !!selected,
  })
  const agents = useQuery({
    queryKey: ['automic-infra-agents', selected?.id, status, platform, team, group, missingHostname],
    queryFn: () => apiGet<InfraAgentsResponse>(`/infrastructure/agents${qs({
      system_id: selected!.id, status, platform, team, group, missing_hostname: missingHostname || undefined,
    })}`),
    enabled: !!selected,
  })
  const awi = useQuery({
    queryKey: ['automic-infra-awi', selected?.id],
    queryFn: () => apiGet<InfraAwiResponse>(`/infrastructure/awi${qs({ system_id: selected!.id })}`),
    enabled: !!selected,
    retry: false,
  })

  const qNorm = search.trim().toLowerCase()
  const agentRows = useMemo(() => {
    const list = (agents.data?.agents ?? []).filter(ag => agentMatchesSearch(ag, qNorm))
    return sortBy(list, sortCol, sortDir, AGENT_SORT)
  }, [agents.data, qNorm, sortCol, sortDir])

  if (systems.isLoading) return <div className="p-6 text-sm text-slate-400">Yükleniyor…</div>
  if (!selected) return <NoSystemNotice />

  const a = agents.data
  const e = engines.data
  const awiServers: AwiServer[] = awi.data?.awi_servers ?? []
  const syncedAt = a?.synced_at ?? e?.synced_at
  const note = a?.note ?? e?.note

  const onSort = (col: string) => {
    const n = toggleSort(sortCol, sortDir, col)
    setSortCol(n.col)
    setSortDir(n.dir)
    set({ asort: n.col, adir: n.dir })
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300"><Boxes size={18} /></div>
          <div>
            <h1 className="text-lg font-semibold text-white">Automic Altyapısı</h1>
            <p className="text-xs text-slate-500">
              Engine sunucuları, agent'lar ve AWI — son kontrol {syncedAt ? `${fmtDateTime(syncedAt, true)} (${fmtAgo(syncedAt)})` : '—'}
            </p>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <SystemPicker systems={systems.data ?? []} value={selected.id} onChange={setSystem} />
          <AutomicInfoButton systemId={selected.id} />
        </div>
      </div>

      {note && <NoticeBox tone="info" text={note} />}
      {a?.infra_warning && <NoticeBox tone="warning" text={a.infra_warning} />}

      <Card title="Engine sunucuları" hint="Automic Automation Engine process'leri (CP/WP/PWP/JWP/JCP/REST) — IP bazında gruplanır. PWP aktif olan sunucu şu an birincil engine'dir.">
        {engines.error ? <ErrorNote error={engines.error} /> : null}
        {!engines.isLoading && !(e?.servers ?? []).length ? <EmptyNote>Kayıt yok</EmptyNote> : null}
        <div className="space-y-2">
          {(e?.servers ?? []).map(s => <EngineServerRow key={s.ip} systemId={selected.id} s={s} />)}
        </div>
      </Card>

      <Card title="Agent'lar" hint="HOST + MQSRV (Type=8) senkronundan. Durum bilgisi anlık değil, son toplama zamanına ait bir çıkarımdır.">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <div className="relative min-w-[14rem] flex-1">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              value={search}
              onChange={ev => { setSearch(ev.target.value); set({ q: ev.target.value || null }) }}
              placeholder="Ara: agent, hostname, IP, grup…"
              className="w-full rounded-lg border border-slate-600 bg-slate-800 py-1.5 pl-8 pr-3 text-sm text-white placeholder-slate-500"
            />
          </div>
          <select value={status} onChange={ev => set({ status: ev.target.value })} style={{ colorScheme: 'dark' }}
            className="rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white">
            {STATUS_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <input value={platform} onChange={ev => set({ platform: ev.target.value || null })} placeholder="Platform (UNIX/WINDOWS…)"
            className="w-40 rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white placeholder-slate-500" />
          <input value={team} onChange={ev => set({ team: ev.target.value || null })} placeholder="Ekip"
            className="w-32 rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white placeholder-slate-500" />
          <input value={group} onChange={ev => set({ group: ev.target.value || null })} placeholder="Agent grubu"
            className="w-36 rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white placeholder-slate-500" />
          <label className="flex items-center gap-1.5 text-xs text-slate-400">
            <input type="checkbox" checked={missingHostname} onChange={ev => set({ missing_hostname: ev.target.checked ? '1' : null })} />
            yalnız hostname atanmamış
          </label>
          <span className="ml-auto text-xs text-slate-500">
            {fmtNumber(agentRows.length)}
            {a && agentRows.length !== a.agents.length ? ` / ${fmtNumber(a.agents.length)}` : ''} agent
          </span>
        </div>
        {agents.error ? <ErrorNote error={agents.error} /> : null}
        {!agents.isLoading && !agentRows.length ? <EmptyNote>Kayıt yok</EmptyNote> : null}
        {agentRows.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-700/60 text-slate-400">
                <tr>
                  <SortTh label="Durum" col="status" active={sortCol} dir={sortDir} onSort={onSort} />
                  <SortTh label="Agent" col="name" active={sortCol} dir={sortDir} onSort={onSort} />
                  <SortTh label="Hostname" col="hostname" active={sortCol} dir={sortDir} onSort={onSort} />
                  <SortTh label="IP" col="ip" active={sortCol} dir={sortDir} onSort={onSort} />
                  <SortTh label="Platform / OS" col="platform" active={sortCol} dir={sortDir} onSort={onSort} />
                  <SortTh label="Gruplar" col="groups" active={sortCol} dir={sortDir} onSort={onSort} />
                  <SortTh label="Son sinyal" col="last_life_sign" active={sortCol} dir={sortDir} onSort={onSort} />
                  <SortTh label="24s çalışma" col="runs_24h" active={sortCol} dir={sortDir} onSort={onSort} />
                </tr>
              </thead>
              <tbody>
                {agentRows.map(ag => (
                  <tr key={ag.name}
                    className={`border-b border-white/[0.04] hover:bg-white/[0.03] ${ag.status === 'disconnected' || ag.status === 'missing' ? 'bg-red-500/[0.04]' : ''}`}>
                    <td className="px-2 py-1.5"><InfraStatusBadge status={ag.status} label={ag.status_label} /></td>
                    <td className="px-2 py-1.5">
                      <Link to={agentPath(selected.id, ag.name)} className="text-slate-100 hover:text-blue-300 hover:underline break-all">
                        {ag.name}
                      </Link>
                    </td>
                    <td className="px-2 py-1.5">
                      {ag.hostname
                        ? <span className="text-slate-300">{ag.hostname}<span className="ml-1 text-[10px] text-slate-500">({ag.hostname_source_label})</span></span>
                        : <span className="text-red-300/80">atanmamış</span>}
                    </td>
                    <td className="px-2 py-1.5 font-mono text-slate-400">{ag.ip ?? '—'}</td>
                    <td className="px-2 py-1.5 text-slate-400">{ag.platform ?? '—'}{ag.os ? ` · ${ag.os}` : ''}</td>
                    <td className="px-2 py-1.5 text-slate-400">{ag.groups?.length ? ag.groups.join(', ') : '—'}</td>
                    <td className="px-2 py-1.5 whitespace-nowrap text-slate-400">
                      {ag.status === 'missing' ? `kayboldu · ${fmtAgo(ag.missing_since)}` : fmtAgo(ag.last_life_sign)}
                    </td>
                    <td className="px-2 py-1.5 whitespace-nowrap text-slate-300">
                      {fmtNumber(ag.runs_24h)}{ag.failed_24h ? <span className="text-red-300"> · {fmtNumber(ag.failed_24h)} hatalı</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>

      {awiServers.length > 0 && (
        <Card title="AWI sunucuları" hint="Automic Web Interface — elle tanımlanan URL'lere periyodik HTTP sağlık kontrolü.">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-700/60 text-slate-400">
                <tr>
                  <th className="px-2 py-2 font-medium">Ad</th>
                  <th className="px-2 py-2 font-medium">URL</th>
                  <th className="px-2 py-2 font-medium">Durum</th>
                  <th className="px-2 py-2 font-medium">HTTP</th>
                  <th className="px-2 py-2 font-medium">Son kontrol</th>
                </tr>
              </thead>
              <tbody>
                {awiServers.map(w => (
                  <tr key={w.id} className="border-b border-white/[0.04]">
                    <td className="px-2 py-1.5 text-slate-200">{w.name}</td>
                    <td className="px-2 py-1.5">
                      <a href={w.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-blue-300 hover:underline break-all">
                        <Globe size={11} />{w.url}
                      </a>
                    </td>
                    <td className="px-2 py-1.5">
                      <InfraStatusBadge status={w.last_status === 'up' ? 'connected' : w.last_status === 'down' ? 'disconnected' : 'unknown'}
                        label={w.last_status ?? 'bilinmiyor'} />
                      {w.last_error && <span className="ml-1.5 text-[11px] text-red-300/80" title={w.last_error}>⚠</span>}
                    </td>
                    <td className="px-2 py-1.5 font-mono text-slate-400">{w.last_http_code ?? '—'}</td>
                    <td className="px-2 py-1.5 whitespace-nowrap text-slate-400">{fmtAgo(w.last_check_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}

function EngineServerRow({ systemId, s }: { systemId: number; s: EngineServer }) {
  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-3">
      <div className="mb-2 flex items-center gap-2">
        <Link to={engineServerPath(systemId, s.ip)} className="font-mono text-sm text-blue-300 hover:underline">{s.ip}</Link>
        {s.node && <span className="text-xs text-slate-400">({s.node})</span>}
        {s.has_active_pwp
          ? <span className="rounded-md border border-green-500/30 bg-green-500/15 px-1.5 py-0.5 text-[11px] text-green-300">PWP aktif</span>
          : <span className="rounded-md border border-amber-500/30 bg-amber-500/15 px-1.5 py-0.5 text-[11px] text-amber-300">PWP yok</span>}
        <span className="ml-auto text-[11px] text-slate-500">{s.processes.length} process</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {s.processes.map(p => (
          <span key={p.name} title={`${p.name} · son sinyal ${fmtAgo(p.last_life_sign)}`}
            className="inline-flex items-center gap-1 rounded-md border border-slate-700/60 bg-slate-800/60 px-1.5 py-0.5 text-[11px]">
            <InfraStatusBadge status={p.status} label={p.process_type} />
            <span className="text-slate-400">{p.name}</span>
            {p.connection_count != null && <span className="text-slate-500">· {p.connection_count} bağlantı</span>}
          </span>
        ))}
      </div>
    </div>
  )
}
