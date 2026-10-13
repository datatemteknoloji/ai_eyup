import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Bot, Box, FileCode2 } from 'lucide-react'
import { agentPath, apiGet, qs, type Execution } from './api'
import {
  AutomicInfoButton, Card, ComponentChart, DependencyGraph, EmptyNote, ErrorNote, ExecutionTable, fmtAgo, fmtDateTime,
  fmtDuration, fmtNumber, KpiTile, LogView, NoticeBox,
} from './ui'

type ObjectSummary = {
  ok: boolean
  error?: string
  system: string
  system_id?: number
  object_name: string
  object_type: string | null
  folder: string | null
  client?: number | null
  period_days: number
  stats: {
    runs: number; failed: number; cancelled: number; failure_rate_pct: number | null
    avg_duration_sec: number | null; p95_duration_sec: number | null; max_duration_sec: number | null; last_end: string | null
  }
  recent_runs: Execution[]
  top_error_signatures: { signature: string; count: number }[]
  agents: { agent: string; runs: number; failed: number }[]
  header?: Record<string, any> | null
  versions?: { version_no: number; content_hash: string; line_count: number; size_bytes: number; fetched_at: string | null }[]
  script_available: boolean
  note?: string
}

type History = { ok: boolean; rows: Record<string, any>[]; label: string; error?: string }

export default function AutomationObject() {
  const { systemId, name } = useParams()
  const sid = Number(systemId)
  const objName = decodeURIComponent(name ?? '')
  const [days, setDays] = useState(30)
  const [tab, setTab] = useState<'runs' | 'script' | 'diff' | 'usage'>('runs')
  const qc = useQueryClient()

  const q = useQuery({
    queryKey: ['automic-object', sid, objName, days],
    queryFn: () => apiGet<ObjectSummary>(`/objects/${sid}/${encodeURIComponent(objName)}${qs({ days })}`),
  })
  const trend = useQuery({
    queryKey: ['automic-object-trend', sid, objName, days],
    queryFn: () => apiGet<History>(`/history/duration_trend${qs({ system_id: sid, object_name: objName, range: `${days}d`, bucket: 'day' })}`),
  })
  const client = q.data?.client ?? q.data?.header?.client
  const script = useQuery({
    queryKey: ['automic-object-script', sid, objName, client],
    queryFn: () => apiGet<any>(`/objects/${sid}/${encodeURIComponent(objName)}/script${qs({ client })}`),
    enabled: tab === 'script' && client != null,
  })
  const diff = useQuery({
    queryKey: ['automic-object-diff', sid, objName, client],
    queryFn: () => apiGet<any>(`/objects/${sid}/${encodeURIComponent(objName)}/diff${qs({ client })}`),
    enabled: tab === 'diff' && client != null,
  })
  const usage = useQuery({
    queryKey: ['automic-object-usage', sid, objName, client],
    queryFn: () => apiGet<any>(`/objects/${sid}/${encodeURIComponent(objName)}/usage${qs({ client, depth: 1 })}`),
    enabled: tab === 'usage' && client != null,
  })
  const refreshScript = useMutation({
    mutationFn: () => apiGet(`/objects/${sid}/${encodeURIComponent(objName)}/script${qs({ client, force: true })}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['automic-object-script', sid, objName] })
      qc.invalidateQueries({ queryKey: ['automic-object', sid, objName] })
    },
  })

  const d = q.data
  const s = d?.stats
  const askQ = `${objName} nesnesinin son ${days} gündeki çalışma ve hata durumunu özetle; süre trendinde sapma var mı?`

  return (
    <div className="space-y-4">
      <Link to={`/automation/executions?system=${sid}&object_name=${encodeURIComponent(objName)}`} className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white">
        <ArrowLeft size={13} /> Bu nesnenin çalışmaları
      </Link>
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300"><Box size={18} /></div>
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-white break-all">{objName}</h1>
            <p className="text-xs text-slate-500">{d ? `${d.system} · ${d.object_type ?? '—'}${d.folder ? ` · ${d.folder}` : ''}` : '…'}</p>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <select value={days} onChange={e => setDays(Number(e.target.value))} style={{ colorScheme: 'dark' }}
            className="rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white">
            {[7, 30, 90].map(n => <option key={n} value={n}>Son {n} gün</option>)}
          </select>
          <AutomicInfoButton systemId={sid} />
          <Link to={`/automation/chat?system=${sid}&q=${encodeURIComponent(askQ)}`}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500">
            <Bot size={14} /> Asistana sor
          </Link>
        </div>
      </div>

      {q.error ? <ErrorNote error={q.error} /> : null}
      {d?.error && <NoticeBox tone="warning" text={d.error} />}

      {d?.header && (
        <Card title="Nesne başlığı (OH)">
          <dl className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
            <div><dt className="text-slate-500">Başlık</dt><dd className="text-slate-200">{d.header.title || '—'}</dd></div>
            <div><dt className="text-slate-500">OH ID</dt><dd className="font-mono text-slate-200">{d.header.object_id ?? '—'}</dd></div>
            <div><dt className="text-slate-500">Değiştiren</dt><dd className="text-slate-200">{d.header.modified_by || '—'}</dd></div>
            <div><dt className="text-slate-500">Değişim</dt><dd className="text-slate-200">{fmtDateTime(d.header.modified_at)}</dd></div>
          </dl>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <KpiTile label="Çalışma" value={fmtNumber(s?.runs)} />
        <KpiTile label="Hatalı" value={fmtNumber(s?.failed)} tone={s?.failed ? 'critical' : undefined} />
        <KpiTile label="Hata oranı" value={s?.failure_rate_pct != null ? `%${s.failure_rate_pct}` : '—'} tone={(s?.failure_rate_pct ?? 0) > 5 ? 'critical' : undefined} />
        <KpiTile label="Ort. süre" value={fmtDuration(s?.avg_duration_sec)} />
        <KpiTile label="p95 / maks" value={<span className="text-sm">{fmtDuration(s?.p95_duration_sec)} / {fmtDuration(s?.max_duration_sec)}</span>} />
        <KpiTile label="Son bitiş" value={<span className="text-sm">{fmtAgo(s?.last_end)}</span>} />
      </div>

      <div className="flex gap-1 border-b border-slate-700/60 text-xs">
        {([['runs', 'Çalışmalar'], ['script', 'Script'], ['diff', 'Sürüm farkı'], ['usage', 'Bağımlılık']] as const).map(([k, l]) => (
          <button key={k} type="button" onClick={() => setTab(k)}
            className={`px-3 py-2 ${tab === k ? 'border-b-2 border-blue-500 text-white' : 'text-slate-400 hover:text-white'}`}>{l}</button>
        ))}
      </div>

      {tab === 'runs' && (
        <>
          <div className="grid gap-3 lg:grid-cols-3">
            <Card title="Süre trendi" className="lg:col-span-2">
              {trend.data?.rows?.length ? (
                <ComponentChart c={{
                  type: 'chart', kind: 'line', x: 'bucket', data: trend.data.rows,
                  series: [{ key: 'avg_sec', label: 'Ortalama (sn)' }, { key: 'p95_sec', label: 'p95 (sn)' }, { key: 'max_sec', label: 'Maks (sn)' }],
                }} />
              ) : <EmptyNote>{trend.isLoading ? 'Yükleniyor…' : 'Veri yok'}</EmptyNote>}
            </Card>
            <div className="space-y-3">
              <Card title="Hata imzaları">
                {d?.top_error_signatures.length ? (
                  <ul className="space-y-1.5">
                    {d.top_error_signatures.map(e => (
                      <li key={e.signature} className="flex items-start gap-2 text-xs">
                        <span className="rounded bg-red-500/15 px-1.5 font-mono text-red-300">{e.count}</span>
                        <span className="font-mono text-slate-300 break-all">{e.signature}</span>
                      </li>
                    ))}
                  </ul>
                ) : <EmptyNote>Hata imzası yok</EmptyNote>}
              </Card>
              <Card title="Agent'lar">
                {d?.agents.length ? (
                  <ul className="space-y-1 text-xs">
                    {d.agents.map(a => (
                      <li key={a.agent} className="flex justify-between">
                        <Link to={agentPath(sid, a.agent)} className="text-blue-300 hover:text-blue-200">{a.agent}</Link>
                        <span className="text-slate-500">{a.runs} çalışma{a.failed ? <span className="text-red-300"> · {a.failed} hata</span> : null}</span>
                      </li>
                    ))}
                  </ul>
                ) : <EmptyNote>—</EmptyNote>}
              </Card>
            </div>
          </div>
          <Card title="Son çalışmalar">
            <ExecutionTable systemId={sid} rows={d?.recent_runs ?? []} compact />
          </Card>
        </>
      )}

      {tab === 'script' && (
        <Card title={<span className="inline-flex items-center gap-1.5"><FileCode2 size={14} /> Script (maskeli)</span>}
          actions={
            <button type="button" disabled={refreshScript.isPending || client == null}
              onClick={() => refreshScript.mutate()}
              className="text-xs text-blue-300 hover:text-blue-200 disabled:opacity-40">Kaynaktan yenile</button>
          }>
          {client == null && <NoticeBox tone="warning" text="Script için client belirlenemedi." />}
          {script.isLoading && <EmptyNote>Yükleniyor…</EmptyNote>}
          {script.error && <ErrorNote error={script.error} />}
          {script.data && !script.data.ok && <NoticeBox tone="warning" text={script.data.error || 'Script alınamadı'} />}
          {script.data?.ok && (
            <>
              <div className="mb-2 flex flex-wrap gap-3 text-[11px] text-slate-500">
                <span>sürüm {script.data.version?.version_no}</span>
                <span>{script.data.version?.line_count} satır</span>
                <span>{script.data.cached ? 'önbellek' : 'yeni'}</span>
                <span className="font-mono">{script.data.version?.content_hash?.slice(0, 12)}…</span>
              </div>
              {d?.versions && d.versions.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1">
                  {d.versions.map(v => (
                    <span key={v.version_no} className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                      v{v.version_no} · {fmtAgo(v.fetched_at)}
                    </span>
                  ))}
                </div>
              )}
              <LogView content={script.data.content || ''} maxHeight="28rem" />
            </>
          )}
        </Card>
      )}

      {tab === 'diff' && (
        <Card title="Sürüm farkı">
          {diff.isLoading && <EmptyNote>Yükleniyor…</EmptyNote>}
          {diff.error && <ErrorNote error={diff.error} />}
          {diff.data?.note && <NoticeBox tone="info" text={diff.data.note} />}
          {diff.data?.diff?.length ? (
            <pre className="max-h-[28rem] overflow-auto rounded-lg bg-slate-950/80 p-3 font-mono text-[11px] leading-relaxed">
              {diff.data.diff.map((line: string, i: number) => (
                <div key={i} className={line.startsWith('+') ? 'text-green-300' : line.startsWith('-') ? 'text-red-300' : 'text-slate-400'}>{line}</div>
              ))}
            </pre>
          ) : !diff.isLoading && <EmptyNote>Fark yok veya tek sürüm</EmptyNote>}
        </Card>
      )}

      {tab === 'usage' && (
        <Card title="Usage / bağımlılık (JPP)">
          {client == null && <NoticeBox tone="warning" text="Bağımlılık için client belirlenemedi." />}
          {usage.isLoading && <EmptyNote>Yükleniyor…</EmptyNote>}
          {usage.error && <ErrorNote error={usage.error} />}
          {usage.data && !usage.data.ok && (
            <NoticeBox tone="warning" text={usage.data.error || 'Usage grafiği alınamadı'} />
          )}
          {usage.data?.ok && usage.data.nodes?.length ? (
            <DependencyGraph
              title={`${objName} · derinlik ${usage.data.depth ?? 1}`}
              nodes={usage.data.nodes}
              edges={usage.data.edges || []}
              systemId={sid}
            />
          ) : usage.data?.ok ? <EmptyNote>Bağımlılık kenarı yok</EmptyNote> : null}
        </Card>
      )}
    </div>
  )
}
