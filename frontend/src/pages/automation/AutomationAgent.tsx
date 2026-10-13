import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Bot, Check, Save, Server } from 'lucide-react'
import { apiGet, apiSend, objectPath, qs, type Execution, type InfraAgentDetail } from './api'
import {
  AutomicInfoButton, Card, EmptyNote, ErrorNote, ExecutionTable, fmtAgo, fmtDateTime, fmtDuration, fmtNumber,
  InfraStatusBadge, KpiTile, NoticeBox,
} from './ui'

type AgentSummary = {
  ok: boolean
  error?: string
  system: string
  agent: string
  stats: {
    runs: number; failed: number; ok: number; failure_rate_pct: number
    avg_duration_sec: number | null; p95_duration_sec: number | null
    last_end: string | null; active_now: number
  }
  top_objects: { object_name: string; object_type: string | null; runs: number; failed: number }[]
  recent_runs: Execution[]
  active: any[]
  note?: string
}

export default function AutomationAgent() {
  const { systemId, name } = useParams()
  const sid = Number(systemId)
  const agent = decodeURIComponent(name ?? '')
  const [range, setRange] = useState('7d')
  const qc = useQueryClient()

  const q = useQuery({
    queryKey: ['automic-agent', sid, agent, range],
    queryFn: () => apiGet<AgentSummary>(`/agents/${sid}/${encodeURIComponent(agent)}${qs({ range })}`),
  })
  const infra = useQuery({
    queryKey: ['automic-agent-infra', sid, agent],
    queryFn: () => apiGet<InfraAgentDetail>(`/infrastructure/agents/${sid}/${encodeURIComponent(agent)}`),
  })
  const d = q.data
  const s = d?.stats
  const idn = infra.data?.identity
  const st = infra.data?.status
  const ctx = infra.data?.context
  const askQ = `${agent} agent'ının son dönemde çalışma ve hata durumunu özetle`

  return (
    <div className="space-y-4">
      <Link to={`/automation?system=${sid}`} className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white">
        <ArrowLeft size={13} /> Genel bakış
      </Link>
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300"><Server size={18} /></div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-semibold text-white break-all">{agent}</h1>
              {st && <InfraStatusBadge status={st.value} label={st.label} />}
            </div>
            <p className="text-xs text-slate-500">{d ? d.system : '…'} · agent aktivitesi</p>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <select value={range} onChange={e => setRange(e.target.value)} style={{ colorScheme: 'dark' }}
            className="rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white">
            {[['24h', '24 saat'], ['7d', '7 gün'], ['30d', '30 gün']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
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
      {d?.note && <NoticeBox tone="info" text={d.note} />}
      {infra.error ? <ErrorNote error={infra.error} /> : null}
      {infra.data?.error && <NoticeBox tone="warning" text={infra.data.error} />}

      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="Kimlik" className="lg:col-span-1">
          {idn ? (
            <dl className="space-y-1.5 text-xs">
              <Item k="IP" v={<span className="font-mono">{idn.ip}</span>} />
              <Item k="Platform" v={idn.platform} />
              <Item k="İşletim sistemi" v={idn.os} />
              <Item k="Donanım" v={idn.hardware} />
              <Item k="Versiyon" v={idn.version} />
              <Item k="Port" v={idn.port} />
              <Item k="Roller" v={idn.roles} />
            </dl>
          ) : <EmptyNote>{infra.isLoading ? 'Yükleniyor…' : 'Kimlik bilgisi yok'}</EmptyNote>}
        </Card>

        <Card title="Durum" className="lg:col-span-1" hint="Durum bilgisi anlık değil; son toplama zamanına ait bir çıkarımdır. Kaynak: Automic DB HOST + MQSRV (Type=8).">
          {st ? (
            <dl className="space-y-1.5 text-xs">
              <Item k="Durum" v={<InfraStatusBadge status={st.value} label={st.label} />} />
              <Item k="Kural" v={st.rule_label} />
              <Item k="Son yaşam sinyali" v={st.last_life_sign ? `${fmtDateTime(st.last_life_sign, true)} (${fmtAgo(st.last_life_sign)})` : null} />
              <Item k="HOST_Active" v={st.host_active} />
              <Item k="Kayboldu" v={st.missing_since ? fmtAgo(st.missing_since) : null} />
              <Item k="Yaklaşık uptime (30g)" v={st.approx_uptime_pct != null ? `%${st.approx_uptime_pct}` : null} />
              <Item k="Son senkron" v={st.synced_at ? fmtAgo(st.synced_at) : null} />
              <div className="pt-1 text-[11px] text-slate-500">{st.uptime_note}</div>
            </dl>
          ) : <EmptyNote>{infra.isLoading ? 'Yükleniyor…' : 'Durum bilgisi yok'}</EmptyNote>}
          {st?.timeline_30d?.length ? <Timeline points={st.timeline_30d} /> : null}
        </Card>

        <Card title="Hostname" className="lg:col-span-1" hint="Sıra: elle atama → Automic HOST_HostName → IP eşlemesi → ters DNS → yalnız IP.">
          {idn ? (
            <HostnameEditor sid={sid} agent={agent} idn={idn} onSaved={() => qc.invalidateQueries({ queryKey: ['automic-agent-infra', sid, agent] })} />
          ) : <EmptyNote>{infra.isLoading ? 'Yükleniyor…' : '—'}</EmptyNote>}
          {(ctx?.groups?.length || ctx?.teams?.length) ? (
            <div className="mt-3 space-y-2 border-t border-white/[0.06] pt-2 text-xs">
              {ctx.groups?.length ? (
                <div><span className="text-slate-500">Gruplar: </span><span className="text-slate-300">{ctx.groups.join(', ')}</span></div>
              ) : null}
              {ctx.teams?.length ? (
                <div><span className="text-slate-500">Ekipler: </span><span className="text-slate-300">{ctx.teams.join(', ')}</span></div>
              ) : null}
            </div>
          ) : null}
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <KpiTile label="Çalışma" value={fmtNumber(s?.runs)} />
        <KpiTile label="Hatalı" value={fmtNumber(s?.failed)} tone={s?.failed ? 'critical' : undefined} />
        <KpiTile label="Hata oranı" value={s ? `%${s.failure_rate_pct}` : '—'} />
        <KpiTile label="Ort. süre" value={fmtDuration(s?.avg_duration_sec)} />
        <KpiTile label="p95" value={fmtDuration(s?.p95_duration_sec)} />
        <KpiTile label="Şu an aktif" value={fmtNumber(s?.active_now)} sub={s?.last_end ? `son ${fmtAgo(s.last_end)}` : null} />
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="En çok çalışan nesneler" className="lg:col-span-1">
          {d?.top_objects.length ? (
            <ul className="space-y-1 text-xs">
              {d.top_objects.map(o => (
                <li key={o.object_name}>
                  <Link to={objectPath(sid, o.object_name)} className="flex justify-between gap-2 hover:text-white text-slate-300">
                    <span className="break-all">{o.object_name}</span>
                    <span className="text-slate-500 whitespace-nowrap">{o.runs}{o.failed ? <span className="text-red-300"> · {o.failed}</span> : null}</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : <EmptyNote>—</EmptyNote>}
        </Card>
        <Card title="Son çalışmalar" className="lg:col-span-2">
          <ExecutionTable systemId={sid} rows={d?.recent_runs ?? []} compact />
        </Card>
      </div>
    </div>
  )
}

function HostnameEditor({ sid, agent, idn, onSaved }: {
  sid: number
  agent: string
  idn: NonNullable<InfraAgentDetail['identity']>
  onSaved: () => void
}) {
  const [value, setValue] = useState(idn.hostname ?? '')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { setValue(idn.hostname ?? '') }, [idn.hostname])

  const save = async () => {
    setSaving(true); setErr(null); setSaved(false)
    try {
      await apiSend(`/infrastructure/agents/${sid}/${encodeURIComponent(agent)}/hostname`, 'PUT', { hostname: value.trim() })
      setSaved(true)
      onSaved()
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <input value={value} onChange={ev => setValue(ev.target.value)} placeholder="hostname"
          className="min-w-0 flex-1 rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white placeholder-slate-500" />
        <button type="button" onClick={save} disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-500 disabled:opacity-50">
          {saved ? <Check size={13} /> : <Save size={13} />} Kaydet
        </button>
      </div>
      {err && <p className="text-[11px] text-red-300">{err}</p>}
      <p className="text-[11px] text-slate-500">Kaynak: {idn.hostname_source_label ?? '—'}</p>
      {idn.hostname_mismatch && (
        <p className="text-[11px] text-amber-300">
          Uyuşmazlık: elle atanan ({idn.hostname_manual}) Automic'teki ({idn.hostname_automic}) ile farklı — elle atama öncelikli gösteriliyor.
        </p>
      )}
    </div>
  )
}

function Timeline({ points }: { points: { at: string; status: string }[] }) {
  const recent = points.slice(-90)
  const color = (s: string) => s === 'connected' ? 'bg-green-500' : s === 'disconnected' ? 'bg-red-500' : s === 'missing' ? 'bg-red-900' : 'bg-amber-500'
  return (
    <div className="mt-3 border-t border-white/[0.06] pt-2">
      <div className="mb-1 text-[11px] text-slate-500">Zaman çizelgesi (son {recent.length} örnek)</div>
      <div className="flex h-4 gap-px overflow-hidden rounded">
        {recent.map((p, i) => (
          <div key={i} title={`${fmtDateTime(p.at, true)} — ${p.status}`} className={`flex-1 ${color(p.status)}`} />
        ))}
      </div>
    </div>
  )
}

function Item({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-slate-500">{k}</dt>
      <dd className="text-right text-slate-200 break-all">{v === null || v === undefined || v === '' ? '—' : v}</dd>
    </div>
  )
}
