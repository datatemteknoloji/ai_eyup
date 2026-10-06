import React, { useState } from 'react'
import { Gauge } from 'lucide-react'
import { useT } from '../i18n/LocaleProvider'
import { GhostButton, NEON, PageHeader, Tabs } from '../components/aiops/ui'
import { Bar, PageInfo, Panel, RunBar, SimpleTable, Stat, apiSend, fmt, pctTone, useInsights } from '../components/insights/insightsKit'

type Cluster = any

function n1Tone(s?: string) {
  return s === 'fail' ? 'text-red-400' : s === 'warn' ? 'text-amber-400' : s === 'ok' ? 'text-emerald-400' : 'text-slate-400'
}

function runwayTxt(f: any, t: (k: any, v?: any) => string) {
  const d = f?.days
  if (!d || d.typical == null) return '—'
  if (d.typical === 0) return t('vi_cap_exceeded')
  return t('vi_cap_days_range', { a: d.fastest ?? d.typical, b: d.typical, c: d.slowest ?? d.typical })
}

function ClusterCard({ c }: { c: Cluster }) {
  const t = useT()
  const n1 = c.n_plus_one || {}
  const n1Label: Record<string, string> = {
    ok: t('vi_n1_ok'), warn: t('vi_n1_warn'), fail: t('vi_n1_fail'), single_host: t('vi_n1_single'), no_data: t('vi_n1_nodata'),
  }
  return (
    <Panel title={<span>{c.cluster} <span className="text-xs text-slate-500 font-normal">· {c.hypervisor} ({c.platform})</span></span>}
      right={<span className={`text-xs font-semibold ${n1Tone(n1.status)}`}>N+1: {n1Label[n1.status] || n1.status}{n1.mem_after_pct != null ? ` (%${fmt(n1.mem_after_pct)})` : ''}</span>}>
      <div className="p-4 grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
        <div className="space-y-1.5">
          <div className="flex justify-between text-slate-400"><span>{t('vi_cap_eff_mem')}</span><span className={`font-mono ${pctTone(c.memory?.effective_used_pct, 75, 85)}`}>%{fmt(c.memory?.effective_used_pct)}</span></div>
          <Bar pct={c.memory?.effective_used_pct} warn={75} crit={85} />
          <div className="text-slate-500 font-mono">{fmt(c.memory?.used_gb)} / {fmt(c.memory?.effective_gb)} GB · {t('vi_cap_reserve')} {fmt(c.memory?.reserved_gb)} GB</div>
          <div className="flex justify-between text-slate-400 pt-2"><span>{t('vi_cap_eff_cpu')}</span><span className={`font-mono ${pctTone(c.cpu?.effective_used_pct, 70, 80)}`}>%{fmt(c.cpu?.effective_used_pct)}</span></div>
          <Bar pct={c.cpu?.effective_used_pct} warn={70} crit={80} />
          <div className="text-slate-500 font-mono">vCPU:core {fmt(c.cpu?.vcpu_ratio, 2)}:1 · {c.vm_powered_on}/{c.vm_count} VM</div>
        </div>
        <div className="space-y-1.5 text-slate-400">
          <div>{t('vi_cap_hosts')}: <span className="font-mono text-slate-200">{c.hosts_usable}/{c.hosts_total}</span>{(c.hosts_excluded || []).length > 0 && <span className="text-slate-500"> ({(c.hosts_excluded || []).map((h: any) => h.host || h).join(', ')})</span>}</div>
          <div>HA: <span className="text-slate-200">{c.ha?.label}</span></div>
          {n1.largest_host && <div>{t('vi_cap_largest')}: <span className="font-mono text-slate-200">{n1.largest_host}</span> ({fmt(n1.largest_host_mem_gb)} GB)</div>}
          <div>{t('vi_cap_runway_mem')}: <span className="text-slate-200">{runwayTxt(c.forecast?.memory, t)}</span></div>
          <div>{t('vi_cap_runway_cpu')}: <span className="text-slate-200">{runwayTxt(c.forecast?.cpu, t)}</span></div>
          {c.network && <div>{t('vi_cap_network')}: <span className="text-slate-200 font-mono">{fmt(c.network.max_util_pct)}%</span></div>}
        </div>
        <div className="space-y-2">
          <div className="text-slate-400">{t('vi_cap_actions')}</div>
          {(c.actions || []).length === 0 && <div className="text-slate-500">{t('vi_cap_no_action')}</div>}
          {(c.actions || []).map((a: any) => (
            <div key={a.step} className="border-l-2 border-blue-600/60 pl-2">
              <div className="text-slate-200 font-medium">{a.step}. {a.title}{a.hosts_needed ? <span className="text-amber-300"> · +{a.hosts_needed} host</span> : null}</div>
              <div className="text-slate-500">{a.detail}</div>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  )
}

function Num({ label, value, onChange, step = '1' }: { label: string; value: string; onChange: (v: string) => void; step?: string }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-slate-400">
      {label}
      <input type="number" min="0" step={step} value={value} onChange={e => onChange(e.target.value)}
        className="w-28 rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white font-mono" />
    </label>
  )
}

function WhatIf() {
  const t = useT()
  const [vcpu, setVcpu] = useState('8')
  const [mem, setMem] = useState('32')
  const [disk, setDisk] = useState('100')
  const [count, setCount] = useState('1')
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState('')
  const run = async () => {
    setErr('')
    try {
      setRes(await apiSend('virt-insights', '/capacity/simulate', 'POST', { vcpu: Number(vcpu), memory_gb: Number(mem), disk_gb: Number(disk), count: Number(count) }))
    } catch (e: any) { setErr(e.message) }
  }
  return (
    <Panel title={t('vi_whatif_title')}>
      <div className="p-4 space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <Num label="vCPU" value={vcpu} onChange={setVcpu} />
          <Num label="Memory (GB)" value={mem} onChange={setMem} />
          <Num label="Disk (GB)" value={disk} onChange={setDisk} />
          <Num label={t('vi_whatif_count')} value={count} onChange={setCount} />
          <GhostButton accent={NEON.blue} onClick={run}>{t('vi_whatif_run')}</GhostButton>
        </div>
        {err && <div className="text-red-300 text-xs">{err}</div>}
        {res && (
          <>
            <SimpleTable rows={res.results || []} cols={[
              { key: 'cluster', label: 'Cluster', render: r => <span className="text-white">{r.cluster} <span className="text-slate-500 text-xs">· {r.hypervisor}</span></span> },
              { key: 'fits', label: t('vi_whatif_fits'), render: r => r.fits ? <span className="text-emerald-400">✓</span> : <span className="text-red-400">✗</span> },
              { key: 'mem', label: t('vi_cap_eff_mem'), render: r => <span className="font-mono">%{fmt(r.before?.memory_effective_pct)} → <span className={pctTone(r.after?.memory_effective_pct, 75, 85)}>%{fmt(r.after?.memory_effective_pct)}</span></span> },
              { key: 'n1', label: 'N+1', render: r => <span className="font-mono">%{fmt(r.before?.n1_memory_pct)} → %{fmt(r.after?.n1_memory_pct)}</span> },
              { key: 'ds', label: 'Datastore', render: r => r.datastore ? <span className="font-mono text-xs">{r.datastore.name} (%{fmt(r.datastore.usage_after_pct)})</span> : '—' },
              { key: 'reasons', label: t('vi_whatif_reasons'), className: 'text-xs text-slate-400', render: r => (r.reasons || []).join(' · ') || '—' },
            ]} />
            <div className="text-[11px] text-slate-500 space-y-0.5">{(res.assumptions || []).map((a: string, i: number) => <div key={i}>• {a}</div>)}</div>
          </>
        )}
      </div>
    </Panel>
  )
}

function Placement() {
  const t = useT()
  const [vm, setVm] = useState('')
  const [vcpu, setVcpu] = useState('4')
  const [mem, setMem] = useState('16')
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState('')
  const run = async () => {
    setErr('')
    try {
      const body = vm.trim() ? { vm_name: vm.trim() } : { vcpu: Number(vcpu), memory_gb: Number(mem) }
      setRes(await apiSend('virt-insights', '/placement', 'POST', body))
    } catch (e: any) { setErr(e.message) }
  }
  return (
    <Panel title={t('vi_place_title')}>
      <div className="p-4 space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-slate-400">{t('vi_place_vm')}
            <input value={vm} onChange={e => setVm(e.target.value)} placeholder={t('vi_place_vm_ph')}
              className="w-56 rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white" />
          </label>
          <span className="text-xs text-slate-500 pb-2">{t('vi_or')}</span>
          <Num label="vCPU" value={vcpu} onChange={setVcpu} />
          <Num label="Memory (GB)" value={mem} onChange={setMem} />
          <GhostButton accent={NEON.blue} onClick={run}>{t('vi_place_run')}</GhostButton>
        </div>
        {err && <div className="text-red-300 text-xs">{err}</div>}
        {res && !res.ok && <div className="text-amber-300 text-xs">{res.error}</div>}
        {res?.ok && (
          <>
            <SimpleTable rows={res.candidates || []} cols={[
              { key: 'host', label: 'Host', render: r => <span className="font-mono text-white">{r.host}</span> },
              { key: 'cluster', label: 'Cluster', render: r => <span>{r.cluster} <span className="text-slate-500 text-xs">· {r.hypervisor}</span></span> },
              { key: 'score', label: t('vi_place_score'), render: r => <span className="font-mono text-blue-300">{fmt(r.score)}</span> },
              { key: 'mem', label: t('vi_place_mem_after'), render: r => <span className={`font-mono ${pctTone(r.metrics?.mem_after_pct, 75, 85)}`}>%{fmt(r.metrics?.mem_after_pct)}</span> },
              { key: 'free', label: t('vi_place_free_mem'), render: r => <span className="font-mono">{fmt(r.metrics?.mem_free_gb)} GB</span> },
              { key: 'n1', label: 'N+1', render: r => r.cluster_n1_after_pct != null ? <span className="font-mono">%{fmt(r.cluster_n1_after_pct)}</span> : '—' },
              { key: 'notes', label: t('vi_whatif_reasons'), className: 'text-xs text-slate-400', render: r => [...(r.penalties || []).map((p: any) => typeof p === 'string' ? p : p.reason || JSON.stringify(p)), r.informational ? t('vi_place_info_only') : ''].filter(Boolean).join(' · ') || '—' },
            ]} />
            {(res.rejected || []).length > 0 && (
              <details className="text-xs text-slate-400"><summary className="cursor-pointer">{t('vi_place_rejected', { n: res.rejected.length })}</summary>
                <div className="mt-2 space-y-0.5">{res.rejected.map((r: any, i: number) => <div key={i}><span className="font-mono">{r.host}</span> ({r.cluster}): {r.reason}</div>)}</div>
              </details>
            )}
            {(res.notes || []).map((n: string, i: number) => <div key={i} className="text-[11px] text-slate-500">• {n}</div>)}
          </>
        )}
      </div>
    </Panel>
  )
}

export default function VirtCapacity() {
  const t = useT()
  const [tab, setTab] = useState('clusters')
  const q = useInsights<any>('virt-insights', '/capacity')
  const sum = useInsights<any>('virt-insights', '/summary')
  const clusters: Cluster[] = q.data?.clusters || []
  const ds: any[] = q.data?.datastores || []
  const n1Fail = clusters.filter(c => c.n_plus_one?.status === 'fail').length
  const hostsNeeded = clusters.reduce((a, c) => a + (c.actions || []).reduce((b: number, x: any) => b + (x.kind === 'invest' ? x.hosts_needed || 0 : 0), 0), 0)
  const dsHot = ds.filter(d => (d.usage_pct ?? 0) > 85).length
  return (
    <div className="space-y-5">
      <PageHeader title={t('vi_cap_page')} titleExtra={<PageInfo id="vi_cap" />} subtitle={t('vi_cap_sub')} actions={<RunBar base="virt-insights" lastRun={sum.data?.last_run} />} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label={t('vi_cap_clusters')} value={clusters.length} />
        <Stat label={t('vi_cap_n1_broken')} value={n1Fail} tone={n1Fail ? 'text-red-400' : 'text-emerald-400'} />
        <Stat label={t('vi_cap_hosts_needed')} value={hostsNeeded} tone={hostsNeeded ? 'text-amber-400' : 'text-white'} />
        <Stat label={t('vi_cap_ds_hot')} value={dsHot} tone={dsHot ? 'text-amber-400' : 'text-white'} />
      </div>
      <Tabs active={tab} onChange={setTab} tabs={[
        { id: 'clusters', label: 'Cluster', count: clusters.length },
        { id: 'datastores', label: 'Datastore', count: ds.length },
        { id: 'whatif', label: t('vi_whatif_tab') },
        { id: 'placement', label: t('vi_place_tab') },
      ]} />
      {q.isLoading && <div className="text-sm text-slate-400">{t('loading')}</div>}
      {q.error && <div className="text-sm text-red-300">{(q.error as Error).message}</div>}
      {tab === 'clusters' && (
        <div className="space-y-3">
          {clusters.length === 0 && !q.isLoading && <Panel><div className="py-10 text-center text-sm text-slate-500"><Gauge className="mx-auto mb-2 opacity-40" />{t('vi_no_rows')}</div></Panel>}
          {clusters.map(c => <ClusterCard key={`${c.hypervisor_id}:${c.cluster}`} c={c} />)}
          {q.data?.method && <div className="text-[11px] text-slate-500">{q.data.method}</div>}
        </div>
      )}
      {tab === 'datastores' && (
        <Panel>
          <SimpleTable rows={ds} cols={[
            { key: 'name', label: 'Datastore', render: r => <span className="text-white font-mono">{r.name}</span> },
            { key: 'hypervisor', label: t('vi_col_source') },
            { key: 'type', label: t('vi_col_type') },
            { key: 'usage_pct', label: t('vi_col_usage'), render: r => <div className="w-32"><div className={`font-mono text-xs ${pctTone(r.usage_pct, 80, 90)}`}>%{fmt(r.usage_pct)}</div><Bar pct={r.usage_pct} warn={80} crit={90} /></div> },
            { key: 'free_gb', label: t('vi_col_free_gb'), render: r => <span className="font-mono">{fmt(r.free_gb)}</span> },
            { key: 'provisioned_pct', label: 'Provisioned %', render: r => <span className={`font-mono ${pctTone(r.provisioned_pct, 100, 150)}`}>{fmt(r.provisioned_pct)}</span> },
            { key: 'runway', label: t('vi_cap_runway'), render: r => runwayTxt(r.forecast, t) },
          ]} />
        </Panel>
      )}
      {tab === 'whatif' && <WhatIf />}
      {tab === 'placement' && <Placement />}
    </div>
  )
}
