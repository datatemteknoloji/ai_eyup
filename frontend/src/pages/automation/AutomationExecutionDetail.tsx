import React, { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Bot, FileText, GitBranch, RotateCcw, Download } from 'lucide-react'
import { agentPath, apiGet, executionPath, qs, type Execution } from './api'
import {
  Card, EmptyNote, ErrorNote, ExecLink, fmtDateTime, fmtDuration, KpiTile, LogView, NoticeBox, ObjectLink,
  StatusBadge, WorkflowTree,
} from './ui'

type Detail = {
  ok: boolean
  system: string
  system_id: number
  data_source: string
  execution: Execution
  error_signature: string | null
  excerpts: { report_type: string; total_lines: number; truncated: boolean; size_bytes: number }[]
  children_count: { total: number; failed: number }
  restarts: Execution[]
  object_stats_30d: { runs: number; failed: number; avg_duration_sec: number | null; p95_duration_sec: number | null }
  /** Agent/ekip altyapı zenginleştirmesi — opsiyonel, API destekliyorsa gelir. */
  infra?: {
    agent_assigned?: string | null
    agent_group?: string | null
    agent_actual?: string | null
    agent_status?: string | null
    agent_status_label?: string | null
    agent_synced_at?: string | null
    server_hostname?: string | null
    server_hostname_source?: string | null
    server_ip?: string | null
    team?: string | null
    team_rule?: string | null
    team_rule_label?: string | null
  } | null
}

type ReportList = { ok: boolean; reports: { report_type: string; total_lines: number | null; truncated?: boolean; stored_excerpt?: boolean }[]; error?: string; data_source?: string }
type Report = { ok: boolean; data_source: string; report_type: string; content: string; total_lines: number; truncated: boolean; error_signature?: string | null; error?: string }
type Children = { ok: boolean; data_source: string; parent_run_id: number; items: Execution[]; failed: Execution[]; error?: string }

export default function AutomationExecutionDetail() {
  const { systemId, client, runId } = useParams()
  const sid = Number(systemId)
  const base = `/executions/${sid}/${client}/${runId}`
  const [tab, setTab] = useState<'reports' | 'children' | 'restarts'>('reports')
  const [reportType, setReportType] = useState<string | null>(null)
  const [fromSource, setFromSource] = useState(false)
  const [liveChildren, setLiveChildren] = useState(false)

  const detail = useQuery({ queryKey: ['automic-exec', base], queryFn: () => apiGet<Detail>(base) })
  const reports = useQuery({
    queryKey: ['automic-exec-reports', base],
    queryFn: () => apiGet<ReportList>(`${base}/reports`),
    enabled: detail.isSuccess,
  })
  const activeType = reportType ?? reports.data?.reports?.[0]?.report_type ?? null
  const report = useQuery({
    queryKey: ['automic-exec-report', base, activeType, fromSource],
    queryFn: () => apiGet<Report>(`${base}/reports/${activeType}${qs({ source: fromSource || undefined, max_lines: 2000 })}`),
    enabled: !!activeType && tab === 'reports',
  })
  const children = useQuery({
    queryKey: ['automic-exec-children', base, liveChildren],
    queryFn: () => apiGet<Children>(`${base}/children${qs({ allow_live: liveChildren || undefined })}`),
    enabled: tab === 'children',
  })

  if (detail.isLoading) return <div className="p-6 text-sm text-slate-400">Yükleniyor…</div>
  if (detail.error) {
    return (
      <div className="space-y-3">
        <BackLink sid={sid} />
        <ErrorNote error={detail.error} />
      </div>
    )
  }
  const d = detail.data!
  const e = d.execution
  const askQ = `RunID ${e.run_id} (client ${e.client}, ${e.object_name}) neden ${e.status_class === 'failed' ? 'hata verdi' : 'bu durumda'}? Rapor ve geçmiş çalışmalara göre değerlendir.`

  const download = () => {
    if (!report.data?.content) return
    const blob = new Blob([report.data.content], { type: 'text/plain;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${e.object_name}_${e.run_id}_${report.data.report_type}.txt`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="space-y-4">
      <BackLink sid={sid} />
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold text-white break-all"><ObjectLink systemId={sid} name={e.object_name} /></h1>
            <StatusBadge cls={e.status_class} code={e.status_code} />
            {e.object_type && <span className="rounded bg-slate-700/60 px-1.5 py-0.5 text-[11px] text-slate-300">{e.object_type}</span>}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {d.system} · client {e.client} · RunID <span className="font-mono">{e.run_id}</span>
            {e.folder && <> · {e.folder}</>}
          </p>
        </div>
        <Link to={`/automation/chat?system=${sid}&q=${encodeURIComponent(askQ)}`}
          className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500">
          <Bot size={14} /> Asistana sor
        </Link>
      </div>

      {d.error_signature && <NoticeBox tone="critical" text={d.error_signature} />}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <KpiTile label="Aktivasyon" value={<span className="text-sm">{fmtDateTime(e.activation_time, true)}</span>} />
        <KpiTile label="Başlangıç" value={<span className="text-sm">{fmtDateTime(e.start_time, true)}</span>} />
        <KpiTile label="Bitiş" value={<span className="text-sm">{fmtDateTime(e.end_time, true)}</span>} />
        <KpiTile label="Süre" value={fmtDuration(e.duration_sec)}
          tone={d.object_stats_30d.p95_duration_sec && e.duration_sec && e.duration_sec > d.object_stats_30d.p95_duration_sec ? 'warning' : undefined}
          sub={d.object_stats_30d.p95_duration_sec ? `p95 ${fmtDuration(d.object_stats_30d.p95_duration_sec)}` : null} />
        <KpiTile label="Agent" value={<span className="text-sm">{e.agent ?? '—'}</span>} sub={e.platform} />
        <KpiTile label="Dönüş kodu" value={e.return_code ?? '—'} tone={e.return_code ? 'critical' : undefined} />
      </div>

      <div className="grid gap-3 lg:grid-cols-4">
        <Card title="Bağlam" className="lg:col-span-1">
          <dl className="space-y-1.5 text-xs">
            <Item k="Kullanıcı" v={e.user} />
            <Item k="Kuyruk" v={e.queue} />
            <Item k="AE çalışma süresi (AH_RunTime)" v={e.run_time_sec != null ? fmtDuration(e.run_time_sec) : null} />
            <Item k="AE tahmini süre (AH_ERT)" v={e.ert_sec ? fmtDuration(e.ert_sec) : null} />
            <Item k="Üst çalışma" v={e.parent_run_id ? <ExecLink systemId={sid} e={{ client: e.client, run_id: e.parent_run_id }} /> : null} />
            <Item k="Kök çalışma" v={e.top_run_id && e.top_run_id !== e.run_id ? <ExecLink systemId={sid} e={{ client: e.client, run_id: e.top_run_id }} /> : null} />
            <Item k="Restart kaynağı" v={e.restart_ref_run_id ? <ExecLink systemId={sid} e={{ client: e.client, run_id: e.restart_ref_run_id }} /> : null} />
            <Item k="Alt adım" v={d.children_count.total ? `${d.children_count.total} (${d.children_count.failed} hatalı)` : null} />
            <div className="border-t border-white/[0.06] pt-1.5 text-slate-500">Son 30 gün</div>
            <Item k="Çalışma" v={d.object_stats_30d.runs} />
            <Item k="Hatalı" v={d.object_stats_30d.failed} />
            <Item k="Ort. süre" v={fmtDuration(d.object_stats_30d.avg_duration_sec)} />
            {d.infra && (
              <>
                <div className="border-t border-white/[0.06] pt-1.5 text-slate-500">Altyapı</div>
                <Item k="Atanan agent/grup" v={d.infra.agent_assigned} />
                <Item k="Çalışan agent" v={d.infra.agent_actual ? (
                  <Link to={agentPath(sid, d.infra.agent_actual)} className="text-blue-300 hover:underline">{d.infra.agent_actual}</Link>
                ) : null} />
                <Item k="Agent durumu" v={d.infra.agent_status_label} />
                <Item k="Sunucu" v={d.infra.server_hostname ?? d.infra.server_ip} />
                <Item k="Ekip" v={d.infra.team ? `${d.infra.team}${d.infra.team_rule_label ? ` (${d.infra.team_rule_label})` : ''}` : null} />
              </>
            )}
          </dl>
        </Card>

        <Card className="lg:col-span-3"
          title={(
            <div className="flex gap-1">
              <TabBtn active={tab === 'reports'} onClick={() => setTab('reports')} icon={<FileText size={13} />}>Raporlar</TabBtn>
              <TabBtn active={tab === 'children'} onClick={() => setTab('children')} icon={<GitBranch size={13} />}>
                Alt adımlar{d.children_count.total ? ` (${d.children_count.total})` : ''}
              </TabBtn>
              <TabBtn active={tab === 'restarts'} onClick={() => setTab('restarts')} icon={<RotateCcw size={13} />}>
                Restart{d.restarts.length ? ` (${d.restarts.length})` : ''}
              </TabBtn>
            </div>
          )}
        >
          {tab === 'reports' && (
            <div className="space-y-2">
              {reports.error ? <ErrorNote error={reports.error} /> : null}
              {reports.data?.error && <NoticeBox tone="warning" text={reports.data.error} />}
              <div className="flex flex-wrap items-center gap-2">
                {(reports.data?.reports ?? []).map(r => (
                  <button key={r.report_type} type="button" onClick={() => { setReportType(r.report_type); setFromSource(false) }}
                    className={`rounded-lg border px-2.5 py-1 text-xs ${activeType === r.report_type ? 'border-blue-500/60 bg-blue-500/15 text-blue-200' : 'border-slate-700 text-slate-400 hover:text-white'}`}>
                    {r.report_type}{r.total_lines ? ` · ${r.total_lines} satır` : ''}{r.stored_excerpt ? ' · kayıtlı' : ''}
                  </button>
                ))}
                {report.data && (
                  <div className="ml-auto flex items-center gap-2 text-[11px] text-slate-500">
                    <span>kaynak: {report.data.data_source}{report.data.truncated ? ` · kırpıldı (${report.data.total_lines} satır)` : ''}</span>
                    {report.data.data_source !== 'source' && (
                      <button type="button" onClick={() => setFromSource(true)} className="rounded border border-slate-700 px-2 py-0.5 text-slate-300 hover:text-white">
                        Kaynaktan oku
                      </button>
                    )}
                    <button type="button" onClick={download} className="rounded border border-slate-700 p-1 text-slate-300 hover:text-white" title="İndir">
                      <Download size={12} />
                    </button>
                  </div>
                )}
              </div>
              {!reports.isLoading && !(reports.data?.reports ?? []).length && <EmptyNote>Bu çalışma için rapor yok</EmptyNote>}
              {report.isLoading && <p className="text-xs text-slate-500">Rapor okunuyor…</p>}
              {report.error ? <ErrorNote error={report.error} /> : null}
              {report.data?.error && <NoticeBox tone="warning" text={report.data.error} />}
              {report.data?.content && <LogView content={report.data.content} />}
              <p className="text-[11px] text-slate-500">Rapor metni gizli bilgi maskelemesinden geçirilerek gösterilir.</p>
            </div>
          )}
          {tab === 'children' && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-[11px] text-slate-500">
                <span>{children.data ? `kaynak: ${children.data.data_source}` : ''}</span>
                <label className="flex items-center gap-1.5">
                  <input type="checkbox" checked={liveChildren} onChange={ev => setLiveChildren(ev.target.checked)} />
                  canlı talep (politika izin verirse)
                </label>
              </div>
              {children.isLoading && <p className="text-xs text-slate-500">Yükleniyor…</p>}
              {children.error ? <ErrorNote error={children.error} /> : null}
              {children.data?.error && <NoticeBox tone="warning" text={children.data.error} />}
              {children.data && <WorkflowTree nodes={children.data.items as any} systemId={sid} />}
            </div>
          )}
          {tab === 'restarts' && (
            d.restarts.length ? (
              <div className="space-y-1">
                {d.restarts.map(r => (
                  <Link key={r.run_id} to={executionPath(sid, r.client, r.run_id)}
                    className="flex items-center gap-3 rounded-lg border border-slate-700/50 px-2.5 py-1.5 text-xs hover:bg-white/[0.03]">
                    <span className="font-mono text-blue-300">{r.run_id}</span>
                    <StatusBadge cls={r.status_class} code={r.status_code} />
                    <span className="text-slate-400">{fmtDateTime(r.end_time)}</span>
                    <span className="ml-auto text-slate-400">{fmtDuration(r.duration_sec)}</span>
                  </Link>
                ))}
              </div>
            ) : <EmptyNote>Restart kaydı yok</EmptyNote>
          )}
        </Card>
      </div>
    </div>
  )
}

function BackLink({ sid }: { sid: number }) {
  return (
    <Link to={`/automation/executions?system=${sid}`} className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white">
      <ArrowLeft size={13} /> Çalışmalar
    </Link>
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

function TabBtn({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs ${active ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}>
      {icon}{children}
    </button>
  )
}
