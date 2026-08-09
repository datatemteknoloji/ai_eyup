/**
 * Topoloji — ainew graph API’sine Atlas tarzı görsel harita.
 * Düğümler kind’e göre gruplanır; seçilince kenar ilişkileri sağ panelde.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Network, RefreshCw, Layers, ExternalLink, Search, X, Boxes, Globe, Server } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'

const KIND_META: Record<string, { short: string; ring: string; text: string }> = {
  deployment: { short: 'D', ring: 'ring-sky-500/60', text: 'text-sky-300' },
  Deployment: { short: 'D', ring: 'ring-sky-500/60', text: 'text-sky-300' },
  service: { short: 'S', ring: 'ring-emerald-500/60', text: 'text-emerald-300' },
  Service: { short: 'S', ring: 'ring-emerald-500/60', text: 'text-emerald-300' },
  route: { short: 'R', ring: 'ring-cyan-500/60', text: 'text-cyan-300' },
  Route: { short: 'R', ring: 'ring-cyan-500/60', text: 'text-cyan-300' },
  pod: { short: 'P', ring: 'ring-amber-500/60', text: 'text-amber-300' },
  Pod: { short: 'P', ring: 'ring-amber-500/60', text: 'text-amber-300' },
  node: { short: 'N', ring: 'ring-slate-500/60', text: 'text-slate-300' },
  Node: { short: 'N', ring: 'ring-slate-500/60', text: 'text-slate-300' },
}

export default function OcpTopologyPanel({
  clusterId,
  project,
  onPickProject,
}: {
  clusterId: number
  project: string
  onPickProject?: () => void
}) {
  const [sel, setSel] = useState<any>(null)
  const [q, setQ] = useState('')

  const { data, isLoading, isFetching, refetch, error } = useQuery({
    queryKey: ['openshift-topology', clusterId, project],
    queryFn: async () => {
      const r = await fetch(
        `${API_BASE_URL}/openshift/clusters/${clusterId}/topology?project=${encodeURIComponent(project)}`,
      )
      if (!r.ok) throw new Error((await r.json()).detail || 'Topology')
      return r.json()
    },
    enabled: !!clusterId && !!project,
  })

  const nodes = useMemo(() => {
    const list = (data?.nodes || []).filter(
      (n: any) => !q.trim() || (n.name || '').toLowerCase().includes(q.toLowerCase()),
    )
    return list
  }, [data, q])

  const groups = useMemo(() => {
    const g: Record<string, any[]> = {}
    for (const n of nodes) {
      const k = (n.kind || 'other').toLowerCase()
      ;(g[k] ||= []).push(n)
    }
    return g
  }, [nodes])

  const related = useMemo(() => {
    if (!sel || !data?.edges) return { out: [] as any[], inn: [] as any[] }
    const out = (data.edges as any[]).filter((e) => e.from === sel.id)
    const inn = (data.edges as any[]).filter((e) => e.to === sel.id)
    const byId = Object.fromEntries((data.nodes || []).map((n: any) => [n.id, n]))
    return {
      out: out.map((e) => ({ ...e, node: byId[e.to] })),
      inn: inn.map((e) => ({ ...e, node: byId[e.from] })),
    }
  }, [sel, data])

  if (!project) {
    return (
      <div className="rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-8 text-center text-sm text-amber-100/90">
        Topoloji için üstten bir <b>Proje</b> seçin
        {onPickProject && (
          <>
            {' '}veya{' '}
            <button type="button" onClick={onPickProject} className="underline">Projeler</button>
          </>
        )}
        .
      </div>
    )
  }

  const NodeBtn = ({ n }: { n: any }) => {
    const m = KIND_META[n.kind] || KIND_META.deployment
    const active = sel?.id === n.id
    const healthy = !n.status || !/fail|error|crash|pending|notready/i.test(String(n.status))
    return (
      <button
        type="button"
        onClick={() => setSel(n)}
        className="flex flex-col items-center gap-1.5 w-[104px] group"
      >
        <span
          className={`relative w-16 h-16 rounded-full grid place-items-center ring-4 transition-all bg-cyber-deep ${
            healthy ? m.ring : 'ring-red-500/70'
          } ${active ? 'scale-110 shadow-lg shadow-black/40' : 'group-hover:scale-105'}`}
        >
          <span className={`text-sm font-bold ${m.text}`}>{m.short}</span>
          {n.host && (
            <span className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-cyber-card ring-2 ring-cyan-500/60 grid place-items-center" title="Route host">
              <ExternalLink size={10} className="text-cyan-300" />
            </span>
          )}
          {n.ready != null && (
            <span className="absolute -bottom-1 px-1.5 rounded-full bg-cyber-card text-[9px] text-slate-300 ring-1 ring-white/10">
              {String(n.ready)}
            </span>
          )}
        </span>
        <span className={`text-[11px] text-center leading-tight truncate w-full ${active ? 'text-slate-100' : 'text-slate-400'}`} title={n.name}>
          {n.name}
        </span>
      </button>
    )
  }

  const order = ['route', 'service', 'deployment', 'pod', 'node']

  return (
    <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-5 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Network size={16} className="text-cyan-400" />
          <h2 className="text-sm font-medium text-white">Topoloji</h2>
          <span className="text-xs text-slate-500 font-mono">{project}</span>
          {data?.summary && (
            <span className="text-[11px] text-slate-600">
              {data.summary.routes} route · {data.summary.services} svc · {data.summary.deployments} deploy · {data.summary.pods} pod
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className="text-xs px-2.5 py-1.5 rounded-lg border border-white/[0.08] text-slate-300 hover:bg-white/[0.04] inline-flex items-center gap-1.5"
        >
          <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} /> Yenile
        </button>
      </div>

      <div className="relative max-w-xs">
        <Search size={14} className="absolute left-2.5 top-2.5 text-slate-500" />
        <input
          className="w-full rounded-lg border border-white/[0.08] bg-cyber-deep/60 pl-8 pr-3 py-2 text-sm text-slate-200 placeholder:text-slate-600"
          placeholder="iş yükü ara…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      {isLoading && <div className="text-sm text-slate-500">Yükleniyor…</div>}
      {error && <div className="text-sm text-red-400">{error instanceof Error ? error.message : 'Hata'}</div>}

      {!isLoading && nodes.length === 0 && (
        <div className="text-sm text-slate-500 py-10 text-center">Bu projede topoloji düğümü yok</div>
      )}

      {nodes.length > 0 && (
        <div className="grid xl:grid-cols-[1fr_300px] gap-4 items-start">
          <div className="rounded-xl border border-white/[0.06] bg-cyber-deep/30 p-4 min-h-[280px] space-y-4">
            {order.filter((k) => groups[k]?.length).map((k) => (
              <div key={k} className="rounded-xl border border-dashed border-white/[0.08] p-4">
                <div className="flex items-center gap-1.5 mb-3">
                  <Layers size={14} className="text-slate-500" />
                  <span className="text-[11px] text-slate-400 uppercase">{k}</span>
                  <span className="text-[10px] text-slate-600">({groups[k].length})</span>
                </div>
                <div className="flex flex-wrap gap-5">
                  {groups[k].map((n: any) => <NodeBtn key={n.id} n={n} />)}
                </div>
              </div>
            ))}
            {Object.keys(groups).filter((k) => !order.includes(k)).map((k) => (
              <div key={k} className="flex flex-wrap gap-5">
                {groups[k].map((n: any) => <NodeBtn key={n.id} n={n} />)}
              </div>
            ))}
          </div>

          <div className="rounded-xl border border-white/[0.06] bg-cyber-deep/40 min-h-[280px]">
            {!sel ? (
              <div className="p-6 text-center">
                <Network size={32} className="mx-auto mb-2 text-slate-700" />
                <p className="text-xs text-slate-500">Ayrıntı için bir düğüm seçin</p>
              </div>
            ) : (
              <div>
                <div className="flex items-center gap-2 px-3 py-2.5 border-b border-white/[0.06]">
                  <span className={`w-6 h-6 rounded-full grid place-items-center text-[10px] font-bold ring-2 bg-cyber-deep ${(KIND_META[sel.kind] || KIND_META.deployment).ring} ${(KIND_META[sel.kind] || KIND_META.deployment).text}`}>
                    {(KIND_META[sel.kind] || KIND_META.deployment).short}
                  </span>
                  <span className="text-sm text-slate-100 truncate">{sel.name}</span>
                  <button type="button" onClick={() => setSel(null)} className="ml-auto text-slate-500 hover:text-slate-300">
                    <X size={16} />
                  </button>
                </div>
                <div className="p-3 space-y-3 text-xs max-h-[26rem] overflow-y-auto">
                  {[
                    ['Tür', sel.kind],
                    ['Durum', sel.status || '—'],
                    ['Host', sel.host || '—'],
                    ['Node', sel.node_name || '—'],
                    ['Ready', sel.ready != null ? String(sel.ready) : '—'],
                    ['Restart', sel.restart_count != null ? String(sel.restart_count) : '—'],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-2 py-1 border-b border-white/[0.04]">
                      <span className="text-slate-500">{k}</span>
                      <span className="text-slate-200 truncate text-right">{v}</span>
                    </div>
                  ))}
                  <div>
                    <p className="text-[11px] font-medium text-slate-400 mb-1 flex items-center gap-1.5">
                      <Boxes size={14} className="text-emerald-400" /> Giden ({related.out.length})
                    </p>
                    <div className="rounded-lg border border-white/[0.06] bg-cyber-deep/40 px-2.5 py-1.5 space-y-1">
                      {related.out.length === 0 && <p className="text-[11px] text-slate-600 py-1">yok</p>}
                      {related.out.map((e: any, i: number) => (
                        <div key={i} className="text-[11px] text-slate-300">
                          —{e.rel}→ <span className="font-mono">{e.node?.name || e.to}</span>
                          <span className="text-slate-600 ml-1">{e.node?.kind}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <p className="text-[11px] font-medium text-slate-400 mb-1 flex items-center gap-1.5">
                      <Server size={14} className="text-sky-400" /> Gelen ({related.inn.length})
                    </p>
                    <div className="rounded-lg border border-white/[0.06] bg-cyber-deep/40 px-2.5 py-1.5 space-y-1">
                      {related.inn.length === 0 && <p className="text-[11px] text-slate-600 py-1">yok</p>}
                      {related.inn.map((e: any, i: number) => (
                        <div key={i} className="text-[11px] text-slate-300">
                          <span className="font-mono">{e.node?.name || e.from}</span> —{e.rel}→
                        </div>
                      ))}
                    </div>
                  </div>
                  {sel.host && (
                    <a
                      href={`https://${sel.host}`}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-cyan-400 hover:text-cyan-300"
                    >
                      <Globe size={12} /> {sel.host}
                    </a>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
