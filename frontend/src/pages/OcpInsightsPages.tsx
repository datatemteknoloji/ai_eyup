import React, { useState } from 'react'
import { useT } from '../i18n/LocaleProvider'
import { GhostButton, NEON, PageHeader, Select, Tabs } from '../components/aiops/ui'
import { ChangesView } from './VirtChanges'
import { Bar, FindingsTable, PageInfo, Panel, RunBar, SimpleTable, Stat, apiSend, fmt, pctTone, useInsights, type Finding } from '../components/insights/insightsKit'

function useSummary() {
  return useInsights<any>('ocp-insights', '/summary')
}


function Num({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-slate-400">
      {label}
      <input type="number" min="0" step="1" value={value} onChange={e => onChange(e.target.value)}
        className="w-28 rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white font-mono" />
    </label>
  )
}

const VERDICT_TONE: Record<string, string> = { ok: 'text-emerald-400', warn: 'text-amber-400', fail: 'text-red-400' }

/** Drain + yeni iş yükü senaryosu (son tarama özetinden; canlı API çağrısı yok). */
function OcpWhatIf({ cluster }: { cluster: any }) {
  const t = useT()
  const [drain, setDrain] = useState<string[]>([])
  const [cpu, setCpu] = useState('2')
  const [mem, setMem] = useState('8')
  const [count, setCount] = useState('0')
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState('')
  const toggle = (n: string) => setDrain(d => d.includes(n) ? d.filter(x => x !== n) : [...d, n])
  const run = async () => {
    setErr('')
    try {
      setRes(await apiSend('ocp-insights', '/capacity/simulate', 'POST', {
        cluster_id: cluster.cluster_id, drain_nodes: drain, cpu_cores: Number(cpu), memory_gb: Number(mem), count: Number(count),
      }))
    } catch (e: any) { setErr(e.message); setRes(null) }
  }
  return (
    <Panel title={`${t('oi_whatif_title')} · ${cluster.cluster}`}>
      <div className="p-4 space-y-4">
        <div>
          <div className="text-xs text-slate-400 mb-1.5">{t('oi_whatif_drain')}</div>
          <div className="flex flex-wrap gap-2">
            {(cluster.workers || []).map((w: any) => (
              <label key={w.name} className={`flex items-center gap-1.5 rounded border px-2 py-1 text-xs font-mono cursor-pointer ${drain.includes(w.name) ? 'border-blue-500/60 text-blue-200 bg-blue-500/10' : 'border-white/[0.08] text-slate-300'}`}>
                <input type="checkbox" checked={drain.includes(w.name)} onChange={() => toggle(w.name)} />{w.name}
              </label>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <Num label={t('oi_whatif_cpu')} value={cpu} onChange={setCpu} />
          <Num label="Memory (GB)" value={mem} onChange={setMem} />
          <Num label={t('oi_whatif_count')} value={count} onChange={setCount} />
          <GhostButton accent={NEON.blue} onClick={run}>{t('vi_whatif_run')}</GhostButton>
        </div>
        {err && <div className="text-red-300 text-xs">{err}</div>}
        {res && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Stat label={t('oi_whatif_verdict')} value={t(`oi_verdict_${res.verdict}` as any)} tone={VERDICT_TONE[res.verdict] || 'text-white'} hint={res.reason} />
              <Stat label={t('oi_req_cpu')} value={`%${fmt(res.before?.cpu_pct)} → %${fmt(res.after?.cpu_pct)}`} tone={pctTone(res.after?.cpu_pct, 85, 100)} />
              <Stat label={t('oi_req_mem')} value={`%${fmt(res.before?.memory_pct)} → %${fmt(res.after?.memory_pct)}`} tone={pctTone(res.after?.memory_pct, 85, 100)} />
              <Stat label={t('oi_whatif_more')} value={res.max_additional ?? '—'} hint={t('oi_whatif_free', { c: fmt(res.free_after?.cpu_cores), m: fmt(res.free_after?.memory_gb) })} />
            </div>
            <div className="text-[11px] text-slate-500 space-y-0.5">{(res.notes || []).map((n: string, i: number) => <div key={i}>• {n}</div>)}</div>
          </div>
        )}
      </div>
    </Panel>
  )
}

export function OcpCapacityPage() {
  const t = useT()
  const sum = useSummary()
  const q = useInsights<any>('ocp-insights', '/capacity')
  const f = useInsights<{ findings: Finding[] }>('ocp-insights', '/findings?category=capacity')
  const clusters: any[] = q.data?.clusters || []
  return (
    <div className="space-y-5">
      <PageHeader title={t('oi_cap_page')} titleExtra={<PageInfo id="oi_cap" />} subtitle={t('oi_cap_sub')} actions={<RunBar base="ocp-insights" lastRun={sum.data?.last_run} />} />
      {q.isLoading && <div className="text-sm text-slate-400">{t('loading')}</div>}
      {clusters.map(c => {
        const n1 = c.n_plus_one || {}
        const n1Tone = n1.status === 'fail' ? 'text-red-400' : n1.status === 'warn' ? 'text-amber-400' : n1.status === 'ok' ? 'text-emerald-400' : 'text-slate-300'
        return (
          <div key={c.cluster_id} className="space-y-3">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Stat label={t('oi_workers')} value={`${c.workers_usable ?? 0}/${c.workers_total ?? 0}`} hint={c.cluster} />
              <Stat label={t('oi_req_cpu')} value={`%${fmt(c.request_pct?.cpu)}`} tone={pctTone(c.request_pct?.cpu, 75, 85)} hint={`${fmt(c.requested?.cpu_cores)} / ${fmt(c.allocatable?.cpu_cores)} core`} />
              <Stat label={t('oi_req_mem')} value={`%${fmt(c.request_pct?.memory)}`} tone={pctTone(c.request_pct?.memory, 75, 85)} hint={`${fmt(c.requested?.memory_gb)} / ${fmt(c.allocatable?.memory_gb)} GB`} />
              <Stat label="N+1" value={n1.status || '—'} tone={n1Tone} hint={n1.largest_worker ? t('oi_n1_hint', { w: n1.largest_worker, m: fmt(n1.memory_after_pct), c: fmt(n1.cpu_after_pct) }) : undefined} />
            </div>
            <Panel title={`${c.cluster} · ${t('oi_workers')}`} right={c.as_of && <span className="text-[11px] text-slate-500">{new Date(c.as_of).toLocaleString()}</span>}>
              <SimpleTable rows={c.workers || []} cols={[
                { key: 'name', label: 'Node', render: r => <span className="font-mono text-white text-xs">{r.name}</span> },
                { key: 'state', label: t('vi_col_result'), render: r => r.ready && r.schedulable ? <span className="text-emerald-400 text-xs">Ready</span> : <span className="text-amber-400 text-xs">{r.ready ? 'Unschedulable' : 'NotReady'}</span> },
                { key: 'pods', label: 'Pod', className: 'font-mono text-slate-300' },
                { key: 'cpu', label: 'CPU request', render: r => <div className="w-36"><div className={`font-mono text-xs ${pctTone(r.cpu_pct, 75, 85)}`}>{fmt(r.req_cpu_cores)} / {fmt(r.cpu_cores)} (%{fmt(r.cpu_pct)})</div><Bar pct={r.cpu_pct} warn={75} crit={85} /></div> },
                { key: 'mem', label: 'Memory request', render: r => <div className="w-40"><div className={`font-mono text-xs ${pctTone(r.mem_pct, 75, 85)}`}>{fmt(r.req_mem_gb)} / {fmt(r.mem_gb)} GB (%{fmt(r.mem_pct)})</div><Bar pct={r.mem_pct} warn={75} crit={85} /></div> },
              ]} />
            </Panel>
            <OcpWhatIf cluster={c} />
          </div>
        )
      })}
      <Panel title={t('oi_cap_findings')}><FindingsTable base="ocp-insights" rows={f.data?.findings || []} showPlatform={false} /></Panel>
      <div className="text-[11px] text-slate-500">{t('oi_cap_method')}</div>
    </div>
  )
}

export function OcpReclaimPage() {
  const t = useT()
  const sum = useSummary()
  const q = useInsights<any>('ocp-insights', '/reclaim')
  const [tab, setTab] = useState('unused')
  const clusters: any[] = q.data?.clusters || []
  const all = (k: string) => clusters.flatMap(c => (c[k] || []).map((r: any) => ({ ...r, cluster: c.cluster })))
  const totals = clusters.reduce((a, c) => ({
    unused: a.unused + (c.summary?.unused || 0), gb: a.gb + (c.summary?.unused_gb || 0),
    unbound: a.unbound + (c.summary?.unbound || 0), over: a.over + (c.summary?.over_request_namespaces || 0),
  }), { unused: 0, gb: 0, unbound: 0, over: 0 })
  const metricsMissing = clusters.some(c => c.summary && c.summary.metrics_available === false)
  const pvcCols = [
    { key: 'pvc', label: 'PVC', render: (r: any) => <span className="font-mono text-white text-xs">{r.pvc}</span> },
    { key: 'cluster', label: 'Cluster', className: 'text-xs text-slate-400' },
    { key: 'size_gb', label: 'GB', className: 'font-mono text-slate-300' },
    { key: 'storage_class', label: 'StorageClass', className: 'text-xs text-slate-300' },
    { key: 'phase', label: 'Phase', className: 'text-xs text-slate-300' },
    { key: 'created', label: t('oi_created'), render: (r: any) => r.created ? new Date(r.created).toLocaleDateString() : '—' },
  ]
  return (
    <div className="space-y-5">
      <PageHeader title={t('oi_rc_page')} titleExtra={<PageInfo id="oi_rc" />} subtitle={t('oi_rc_sub')} actions={<RunBar base="ocp-insights" lastRun={sum.data?.last_run} />} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label={t('oi_rc_unused')} value={totals.unused} hint={`${fmt(totals.gb, 0)} GB`} tone={totals.unused ? 'text-amber-400' : 'text-white'} />
        <Stat label={t('oi_rc_unbound')} value={totals.unbound} tone={totals.unbound ? 'text-amber-400' : 'text-white'} />
        <Stat label={t('oi_rc_over')} value={totals.over} tone={totals.over ? 'text-amber-400' : 'text-white'} />
        <Stat label="Cluster" value={clusters.length} />
      </div>
      {metricsMissing && <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 px-4 py-2 text-xs text-blue-200">{t('oi_rc_no_metrics')}</div>}
      <Tabs active={tab} onChange={setTab} tabs={[
        { id: 'unused', label: t('oi_rc_unused'), count: totals.unused },
        { id: 'unbound', label: t('oi_rc_unbound'), count: totals.unbound },
        { id: 'over_request', label: t('oi_rc_over'), count: totals.over },
      ]} />
      <Panel>
        {tab !== 'over_request' ? <SimpleTable rows={all(tab)} cols={pvcCols} /> : (
          <SimpleTable rows={all('over_request')} cols={[
            { key: 'namespace', label: 'Namespace', render: (r: any) => <span className="font-mono text-white text-xs">{r.namespace}</span> },
            { key: 'cluster', label: 'Cluster', className: 'text-xs text-slate-400' },
            { key: 'cpu', label: 'CPU (request → use)', render: (r: any) => <span className="font-mono">{fmt(r.req_cpu_cores)} → {fmt(r.use_cpu_cores, 2)}</span> },
            { key: 'mem', label: 'Memory GB (request → use)', render: (r: any) => <span className="font-mono">{fmt(r.req_mem_gb)} → {fmt(r.use_mem_gb)}</span> },
          ]} />
        )}
      </Panel>
      <div className="text-[11px] text-slate-500">{t('oi_rc_note')}</div>
    </div>
  )
}


const RISK_TONE: Record<string, string> = { high: 'text-red-400', medium: 'text-amber-400', low: 'text-slate-300' }

/** Node risk kartı: son günlerde tekrar eden NotReady / baskı / reboot olayları (tahmin yok). */
function NodeRisk() {
  const t = useT()
  const [days, setDays] = useState('7')
  const q = useInsights<any>('ocp-insights', `/node-risk?days=${days}`)
  const rows: any[] = q.data?.nodes || []
  return (
    <Panel title={t('oi_risk_title')} right={
      <Select value={days} onChange={setDays}>
        {['1', '7', '30'].map(d => <option key={d} value={d}>{t('vi_ch_days', { n: d })}</option>)}
      </Select>
    }>
      <SimpleTable rows={rows} empty={t('oi_risk_none')} cols={[
        { key: 'node', label: 'Node', render: r => <span className="font-mono text-white text-xs">{r.node}</span> },
        { key: 'cluster', label: 'Cluster', className: 'text-xs text-slate-400' },
        { key: 'level', label: t('oi_risk_level'), render: r => <span className={`font-mono text-xs ${RISK_TONE[r.level]}`}>{r.level} ({r.score})</span> },
        { key: 'now', label: t('oi_risk_now'), render: r => r.unhealthy_now ? <span className="text-red-400 text-xs">{(r.now || []).join(', ')}</span> : <span className="text-emerald-400 text-xs">OK</span> },
        { key: 'counts', label: t('oi_risk_events'), className: 'text-xs text-slate-300', render: r => Object.entries(r.counts || {}).map(([k, v]) => `${k} ×${v}`).join(' · ') },
        { key: 'last', label: t('oi_risk_last'), render: r => r.last_event ? new Date(r.last_event).toLocaleString() : '—' },
      ]} />
      <div className="px-4 pb-3 text-[11px] text-slate-500">{t('oi_risk_note')}</div>
    </Panel>
  )
}

export function OcpHealthPage() {
  const t = useT()
  const sum = useSummary()
  const [cat, setCat] = useState('health')
  const [result, setResult] = useState('fail')
  const q = useInsights<{ findings: Finding[] }>('ocp-insights', `/findings?category=${cat}&result=${result}`)
  const by = sum.data?.findings?.by_category || {}
  const comp = (sum.data?.clusters || []).find((c: any) => c.compliance)?.compliance
  const label: Record<string, string> = {
    health: t('oi_hc_operators'), drift: 'MachineConfigPool', upgrade: t('vi_cat_upgrade'), compliance: 'Compliance Operator',
  }
  return (
    <div className="space-y-5">
      <PageHeader title={t('oi_hc_page')} titleExtra={<PageInfo id="oi_hc" />} subtitle={t('oi_hc_sub')} actions={<RunBar base="ocp-insights" lastRun={sum.data?.last_run} />} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {(sum.data?.clusters || []).map((c: any) => (
          <Stat key={c.cluster_id} label={c.cluster} value={c.version || '—'} hint={c.as_of ? new Date(c.as_of).toLocaleString() : undefined} tone="text-blue-300" />
        ))}
        <Stat label="Compliance Operator" value={comp?.installed ? `${comp.fail} fail` : t('oi_hc_no_co')} tone={comp?.fail ? 'text-red-400' : 'text-slate-300'} />
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        <Tabs active={cat} onChange={setCat} tabs={['health', 'drift', 'upgrade', 'compliance'].map(c => ({ id: c, label: label[c], count: by[c]?.total ?? 0 }))} />
        <Select value={result} onChange={setResult}>
          <option value="fail">{t('vi_res_fail')}</option>
          <option value="pass">{t('vi_res_pass')}</option>
          <option value="all">{t('vi_all')}</option>
        </Select>
      </div>
      <Panel>
        {q.isLoading ? <div className="p-6 text-sm text-slate-400">{t('loading')}</div> : <FindingsTable base="ocp-insights" rows={q.data?.findings || []} showPlatform={false} />}
      </Panel>
      {cat === 'health' && <NodeRisk />}
    </div>
  )
}

export function OcpChangesPage() {
  return <ChangesView base="ocp-insights" />
}
