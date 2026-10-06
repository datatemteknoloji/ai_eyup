import React, { useState } from 'react'
import { useT } from '../i18n/LocaleProvider'
import { PageHeader, Tabs } from '../components/aiops/ui'
import { FindingsTable, PageInfo, Panel, RunBar, SimpleTable, Stat, fmt, useInsights } from '../components/insights/insightsKit'

function fileFlags(r: any, t: (k: any) => string) {
  const e = r.extra || {}
  const f: string[] = []
  if (e.delta) f.push(t('vi_rc_flag_delta'))
  if (e.replica_suspect) f.push(t('vi_rc_flag_replica'))
  if (e.content_library) f.push('Content Library')
  if (e.recent) f.push(t('vi_rc_flag_recent'))
  if (e.shared_datastore) f.push(t('vi_rc_flag_shared'))
  return f.join(' · ') || '—'
}

export default function VirtReclaim() {
  const t = useT()
  const [tab, setTab] = useState('powered_off')
  const q = useInsights<any>('virt-insights', '/reclaim')
  const sum = useInsights<any>('virt-insights', '/summary')
  const d = q.data || {}
  const s = d.summary || {}
  const vmCols = [
    { key: 'vm', label: 'VM', render: (r: any) => <span className="text-white">{r.vm}</span> },
    { key: 'cluster', label: 'Cluster', render: (r: any) => <span>{r.cluster || '—'} <span className="text-slate-500 text-xs">· {r.hypervisor}</span></span> },
    { key: 'vcpu', label: 'vCPU', className: 'font-mono text-slate-300' },
    { key: 'memory_gb', label: 'Memory GB', className: 'font-mono text-slate-300' },
  ]
  const tabs = [
    { id: 'powered_off', label: t('vi_rc_off'), count: s.powered_off?.count ?? 0 },
    { id: 'idle', label: t('vi_rc_idle'), count: s.idle?.count ?? 0 },
    { id: 'oversized', label: t('vi_rc_oversized'), count: s.oversized?.count ?? 0 },
    { id: 'snapshots', label: 'Snapshot', count: s.snapshots?.count ?? 0 },
    { id: 'orphans', label: t('vi_rc_orphans'), count: s.orphans?.count ?? 0 },
    { id: 'isos', label: 'ISO', count: s.isos?.count ?? 0 },
    { id: 'unused_datastores', label: t('vi_rc_unused_ds'), count: s.unused_datastores?.count ?? 0 },
  ]
  return (
    <div className="space-y-5">
      <PageHeader title={t('vi_rc_page')} titleExtra={<PageInfo id="vi_rc" />} subtitle={t('vi_rc_sub')} actions={<RunBar base="virt-insights" lastRun={sum.data?.last_run} />} />
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Stat label={t('vi_rc_off_mem')} value={`${fmt(s.powered_off?.memory_gb, 0)} GB`} hint={t('vi_rc_vm_count', { n: s.powered_off?.count ?? 0 })} />
        <Stat label={t('vi_rc_rightsize_mem')} value={`${fmt((s.idle?.memory_gb ?? 0) + (s.oversized?.memory_reclaimable_gb ?? 0), 0)} GB`} hint={`vCPU ${fmt((s.idle?.vcpu ?? 0) + (s.oversized?.vcpu_reclaimable ?? 0), 0)}`} />
        <Stat label={t('vi_rc_snap_gb')} value={`${fmt(s.snapshots?.space_gb, 0)} GB`} hint={t('vi_rc_vm_count', { n: s.snapshots?.count ?? 0 })} tone={(s.snapshots?.count ?? 0) ? 'text-amber-400' : 'text-white'} />
        <Stat label={t('vi_rc_orphan_gb')} value={`${fmt(s.orphans?.size_gb, 0)} GB`} hint={t('vi_rc_file_count', { n: s.orphans?.count ?? 0 })} tone={(s.orphans?.count ?? 0) ? 'text-amber-400' : 'text-white'} />
        <Stat label={t('vi_rc_storage_total')} value={`${fmt(s.storage_total_gb, 0)} GB`} tone="text-blue-300" />
      </div>
      {(d.notes || []).length > 0 && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-2 text-xs text-amber-200 space-y-0.5">
          {(d.notes || []).map((n: string, i: number) => <div key={i}>• {n}</div>)}
        </div>
      )}
      <Tabs tabs={tabs} active={tab} onChange={setTab} />
      {q.isLoading && <div className="text-sm text-slate-400">{t('loading')}</div>}
      {q.error && <div className="text-sm text-red-300">{(q.error as Error).message}</div>}
      <Panel>
        {tab === 'powered_off' && <SimpleTable rows={d.powered_off || []} cols={[...vmCols,
          { key: 'disk_gb', label: 'Disk GB', className: 'font-mono text-slate-300' },
          { key: 'off_days', label: t('vi_rc_off_days'), render: (r: any) => r.off_days != null ? <span className="font-mono">{r.off_days}</span> : <span className="text-slate-500">≥ {r.off_days_min}</span> },
          { key: 'last_on', label: t('vi_rc_last_on'), render: (r: any) => r.last_on ? new Date(r.last_on).toLocaleDateString() : '—' },
        ]} />}
        {tab === 'idle' && <SimpleTable rows={d.idle || []} cols={[...vmCols,
          { key: 'avg_cpu_pct', label: 'CPU avg %', className: 'font-mono text-slate-300' },
          { key: 'p95_cpu_pct', label: 'CPU p95 %', className: 'font-mono text-slate-300' },
          { key: 'avg_mem_pct', label: 'Memory avg %', className: 'font-mono text-slate-300' },
          { key: 'suggest', label: t('vi_rc_suggest'), render: (r: any) => <span className="font-mono text-blue-300">{fmt(r.rightsize?.vcpu ?? r.vcpu)} vCPU · {fmt(r.rightsize?.memory_gb ?? r.memory_gb)} GB</span> },
        ]} />}
        {tab === 'oversized' && <SimpleTable rows={d.oversized || []} cols={[...vmCols,
          { key: 'avg_cpu_pct', label: 'CPU avg %', className: 'font-mono text-slate-300' },
          { key: 'p95_cpu_pct', label: 'CPU p95 %', className: 'font-mono text-slate-300' },
          { key: 'suggest', label: t('vi_rc_suggest'), render: (r: any) => <span className="font-mono text-blue-300" title={r.rightsize?.basis}>{fmt(r.rightsize?.vcpu ?? r.vcpu)} vCPU · {fmt(r.rightsize?.memory_gb ?? r.memory_gb)} GB</span> },
        ]} />}
        {tab === 'snapshots' && <FindingsTable base="virt-insights" rows={d.snapshots || []} />}
        {(tab === 'orphans' || tab === 'isos') && <SimpleTable rows={d[tab] || []} cols={[
          { key: 'name', label: t('vi_rc_file'), render: (r: any) => <span className="font-mono text-white text-xs" title={r.path}>{r.name}</span> },
          { key: 'datastore', label: 'Datastore', className: 'text-xs text-slate-300' },
          { key: 'platform', label: t('vi_col_source'), className: 'text-xs text-slate-400' },
          { key: 'size_gb', label: 'GB', className: 'font-mono text-slate-300' },
          { key: 'modified_at', label: t('vi_rc_modified'), render: (r: any) => r.modified_at ? new Date(r.modified_at).toLocaleDateString() : '—' },
          { key: 'flags', label: t('vi_rc_flags'), className: 'text-xs text-amber-300', render: (r: any) => fileFlags(r, t) },
        ]} />}
        {tab === 'unused_datastores' && <SimpleTable rows={d.unused_datastores || []} cols={[
          { key: 'name', label: 'Datastore', render: (r: any) => <span className="font-mono text-white">{r.name}</span> },
          { key: 'hypervisor', label: t('vi_col_source') },
          { key: 'capacity_gb', label: 'GB', className: 'font-mono text-slate-300' },
          { key: 'usage_pct', label: t('vi_col_usage'), className: 'font-mono text-slate-300' },
          { key: 'note', label: t('vi_col_detail'), className: 'text-xs text-slate-400' },
        ]} />}
      </Panel>
      {d.criteria && (
        <div className="text-[11px] text-slate-500 space-y-0.5">
          {Object.entries(d.criteria).map(([k, v]) => <div key={k}><span className="text-slate-400">{k}</span>: {String(v)}</div>)}
        </div>
      )}
    </div>
  )
}
