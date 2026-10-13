import React, { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Gauge } from 'lucide-react'
import { useT } from '../i18n/LocaleProvider'
import { GhostButton, NEON, PageHeader, Tabs } from '../components/aiops/ui'
import { MethodBadge } from '../components/insights/MethodBadge'
import WhatIfResults from '../components/insights/WhatIfResults'
import HostFailure from '../components/insights/HostFailure'
import ReclaimSim from '../components/insights/ReclaimSim'
import BulkPlacement from '../components/insights/BulkPlacement'
import PolicyOverrides from '../components/insights/PolicyOverrides'
import { InfoDot, TermHint } from '../components/insights/InfoDot'
import { Bar, PageInfo, Panel, RunBar, SimpleTable, Stat, apiGet, apiSend, fmt, pctTone, useInsights } from '../components/insights/insightsKit'

type Cluster = any

function n1Tone(s?: string) {
  return s === 'fail' ? 'text-red-400' : s === 'warn' ? 'text-amber-400' : s === 'ok' ? 'text-emerald-400' : 'text-slate-400'
}

/** Tek host / veri yok: "N+1 uygulanamaz" (ölçülemedi değil). */
function n1IsNotApplicable(s?: string) {
  return s === 'single_host'
}

function runwayTxt(f: any, t: (k: any, v?: any) => string) {
  if (!f) return '—'
  const st = f.state
  if (st === 'insufficient_data') return t('vi_rw_insufficient', { n: f.data_days ?? 0, w: f.window_days ?? 90, m: f.min_days ?? 14 })
  if (st === 'low_confidence') return t('vi_rw_low', { n: f.data_days ?? 0, w: f.window_days ?? 90 })
  if (st === 'flat') return t('vi_rw_flat')
  if (st === 'no_current') return t('vi_rw_no_current')
  if (st === 'exceeded') return t('vi_cap_exceeded')
  const d = f.days
  if (!d || d.typical == null) return '—'
  if (d.typical === 0) return t('vi_cap_exceeded')
  return t('vi_cap_days_range', { a: d.fastest ?? d.typical, b: d.typical, c: d.slowest ?? d.typical })
}

/** Cluster'ın erişebildiği datastore'ların runway'i: en kötüsü + liste. Ortak datastore toplanmaz. */
function DatastoreRunway({ dr }: { dr: any }) {
  const t = useT()
  const label = <span className="inline-flex items-center">{t('vi_rw_ds')}<TermHint k="ds_runway" /></span>
  if (dr.state !== 'ok') {
    return <div data-testid="ds-runway-na">{label}: <span className="text-slate-500">{t(`vi_rw_ds_un_${dr.reason}` as any)}</span></div>
  }
  const lead = dr.worst
    ? { name: dr.worst.name, txt: runwayTxt({ days: dr.worst.days }, t) }
    : { name: dr.items[0].name, txt: runwayTxt(dr.items[0].forecast, t) }
  return (
    <div data-testid="ds-runway">
      <div>{label}: <span className="text-slate-200">{t('vi_rw_ds_worst', lead)}</span> <span className="text-slate-500">· {t('vi_rw_thr', { thr: fmt(dr.threshold) })}</span></div>
      <details className="text-slate-500">
        <summary className="cursor-pointer">{t('vi_rw_ds_list', { n: dr.items.length })}</summary>
        <div className="mt-1 space-y-0.5 font-mono text-[11px]">
          {dr.items.map((i: any) => (
            <div key={i.name} data-testid="ds-runway-item">
              {i.name} · %{fmt(i.usage_pct)} · {runwayTxt(i.forecast, t)}{i.access === 'cluster_config' ? ` · ${t('vi_rw_ds_access_cluster')}` : ''}
            </div>
          ))}
        </div>
      </details>
    </div>
  )
}

function ClusterCard({ c }: { c: Cluster }) {
  const t = useT()
  const n1 = c.n_plus_one || {}
  const n1Label: Record<string, string> = {
    ok: t('vi_n1_ok'), warn: t('vi_n1_warn'), fail: t('vi_n1_fail'), single_host: t('vi_n1_single'), no_data: t('vi_n1_nodata'),
  }
  return (
    <Panel title={<span>{c.cluster} <span className="text-xs text-slate-500 font-normal">· {c.hypervisor} ({c.platform})</span></span>}
      right={n1IsNotApplicable(n1.status)
        ? <span title={t('vi_n1_single_hint')} className="text-xs font-semibold text-slate-400 border border-dashed border-slate-500/40 rounded px-1.5 py-0.5">N+1: {t('vi_res_na')}<TermHint k="n1" /></span>
        : <span className={`text-xs font-semibold ${n1Tone(n1.status)}`}>N+1: {n1Label[n1.status] || n1.status}{n1.mem_after_pct != null ? ` (%${fmt(n1.mem_after_pct)})` : ''}<TermHint k="n1" /></span>}
      method="cap.cluster.n_plus_one" methodAt={c.as_of}>
      <div className="p-4 grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
        <div className="space-y-1.5">
          <div className="flex justify-between text-slate-400"><span>{t('vi_cap_eff_mem')} <MethodBadge id="cap.cluster.effective" at={c.as_of} /></span><span className={`font-mono ${pctTone(c.memory?.effective_used_pct, 75, 85)}`}>%{fmt(c.memory?.effective_used_pct)}</span></div>
          <Bar pct={c.memory?.effective_used_pct} warn={75} crit={85} />
          <div className="text-slate-500 font-mono">{fmt(c.memory?.used_gb)} / {fmt(c.memory?.effective_gb)} GB · {t('vi_cap_reserve')} {fmt(c.memory?.reserved_gb)} GB</div>
          <div className="flex justify-between text-slate-400 pt-2"><span>{t('vi_cap_eff_cpu')} <MethodBadge id="cap.cluster.effective" at={c.as_of} /></span><span className={`font-mono ${pctTone(c.cpu?.effective_used_pct, 70, 80)}`}>%{fmt(c.cpu?.effective_used_pct)}</span></div>
          <Bar pct={c.cpu?.effective_used_pct} warn={70} crit={80} />
          <div className="text-slate-500 font-mono">vCPU:core {fmt(c.cpu?.vcpu_ratio, 2)}:1<TermHint k="vcpu_ratio" /> · {c.vm_powered_on}/{c.vm_count} VM <MethodBadge id="cap.cluster.vcpu_ratio" at={c.as_of} /></div>
        </div>
        <div className="space-y-1.5 text-slate-400">
          <div>{t('vi_cap_hosts')}: <span className="font-mono text-slate-200">{c.hosts_usable}/{c.hosts_total}</span>{(c.hosts_excluded || []).length > 0 && <span className="text-slate-500"> ({(c.hosts_excluded || []).map((h: any) => h.host || h).join(', ')})</span>}</div>
          <div className="inline-flex items-center">HA: <span className="text-slate-200 ml-1">{c.ha?.label}</span><TermHint k="ha_reserve" /></div>
          {n1.largest_host && <div>{t('vi_cap_largest')}: <span className="font-mono text-slate-200">{n1.largest_host}</span> ({fmt(n1.largest_host_mem_gb)} GB)</div>}
          <div><span className="inline-flex items-center">{t('vi_cap_runway_mem')}<TermHint k="runway" /></span>: <span className="text-slate-200">{runwayTxt(c.forecast?.memory, t)}</span> {c.forecast?.memory?.threshold != null && <span className="text-slate-500">· {t('vi_rw_thr', { thr: fmt(c.forecast.memory.threshold) })}</span>} <MethodBadge id="cap.cluster.mem_runway" at={c.as_of} /></div>
          <div><span className="inline-flex items-center">{t('vi_cap_runway_cpu')}<TermHint k="runway" /></span>: <span className="text-slate-200">{runwayTxt(c.forecast?.cpu, t)}</span> {c.forecast?.cpu?.threshold != null && <span className="text-slate-500">· {t('vi_rw_thr', { thr: fmt(c.forecast.cpu.threshold) })}</span>} <MethodBadge id="cap.cluster.cpu_runway" at={c.as_of} /></div>
          {c.datastore_runway && <><DatastoreRunway dr={c.datastore_runway} /> <MethodBadge id="cap.cluster.ds_runway" at={c.as_of} /></>}
          {c.network && <div>{t('vi_cap_network')}: <span className="text-slate-200 font-mono">{fmt(c.network.max_util_pct)}%</span></div>}
        </div>
        <div className="space-y-2">
          <div className="text-slate-400">{t('vi_cap_actions')} <MethodBadge id="cap.actions" at={c.as_of} /></div>
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

function Num({ label, value, onChange, step = '1', hint }: { label: string; value: string; onChange: (v: string) => void; step?: string; hint?: string }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-slate-400">
      <span className="inline-flex items-center">{label}{hint && <TermHint k={hint} />}</span>
      <input type="number" min="0" step={step} value={value} onChange={e => onChange(e.target.value)}
        className="w-28 rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white font-mono" />
    </label>
  )
}

type VmOpt = { name: string; hypervisor?: string; cluster?: string; vcpu?: number; memory_gb?: number; disk_gb?: number }

/** Aranabilir VM seçici (envanterden; elle yazım yok — yalnız listeden eşleşen ad geçerli sayılır). */
function VmPicker({ label, placeholder, onPick, listId }: { label: string; placeholder: string; onPick: (vm: VmOpt | null) => void; listId: string }) {
  const [q, setQ] = useState('')
  const [opts, setOpts] = useState<VmOpt[]>([])
  useEffect(() => {
    let cancelled = false
    const tmr = setTimeout(async () => {
      try {
        const r = await apiGet<any>('virt-insights', `/vms?q=${encodeURIComponent(q.trim())}&limit=40`)
        if (!cancelled) setOpts(r.items || [])
      } catch { if (!cancelled) setOpts([]) }
    }, 250)
    return () => { cancelled = true; clearTimeout(tmr) }
  }, [q])
  return (
    <label className="flex flex-col gap-1 text-xs text-slate-400">{label}
      <input list={listId} value={q} placeholder={placeholder}
        onChange={e => {
          const v = e.target.value
          setQ(v)
          onPick(opts.find(o => o.name === v) || null)
        }}
        className="w-64 rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white" />
      <datalist id={listId}>
        {opts.map(o => (
          <option key={`${o.name}-${o.hypervisor}-${o.cluster}`} value={o.name}>{[o.hypervisor, o.cluster].filter(Boolean).join(' · ')}</option>
        ))}
      </datalist>
    </label>
  )
}

/** H.0 kapsam seçici: instance → datacenter → cluster(lar) → (opsiyonel) host(lar). Seçim yoksa her cluster bağımsız. */
export function ScopeSelect({ clusters, value, onChange, showHosts = true }: { clusters: Cluster[]; value: Scope; onChange: (s: Scope) => void; showHosts?: boolean }) {
  const t = useT()
  const inst = Array.from(new Map(clusters.map((c: any) => [c.hypervisor_id, c.hypervisor])).entries())
  const inInst = clusters.filter((c: any) => !value.instance || String(c.hypervisor_id) === value.instance)
  const dcs = Array.from(new Set(inInst.map((c: any) => c.datacenter).filter(Boolean))) as string[]
  const inDc = inInst.filter((c: any) => !value.datacenter || c.datacenter === value.datacenter)
  const cls = Array.from(new Set(inDc.map((c: any) => c.cluster))) as string[]
  const hosts = Array.from(new Set(inDc.filter((c: any) => !value.clusters.length || value.clusters.includes(c.cluster))
    .flatMap((c: any) => c.host_names || []))) as string[]
  const sel = 'rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white'
  const multi = (opts: string[], cur: string[], set: (v: string[]) => void, testId: string) => (
    <select multiple data-testid={testId} value={cur} className={`${sel} h-20 min-w-[10rem]`}
      onChange={e => set(Array.from(e.target.selectedOptions).map(o => o.value))}>
      {opts.map(o => <option key={o} value={o}>{o}</option>)}
    </select>
  )
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-start gap-3">
        <label className="flex flex-col gap-1 text-xs text-slate-400">{t('vi_scope_instance')}
          <select data-testid="scope-instance" value={value.instance} className={sel}
            onChange={e => onChange({ instance: e.target.value, datacenter: '', clusters: [], hosts: [] })}>
            <option value="">{t('vi_scope_all')}</option>
            {inst.map(([id, name]) => <option key={String(id)} value={String(id)}>{String(name)}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">{t('vi_scope_dc')}
          <select data-testid="scope-dc" value={value.datacenter} className={sel} disabled={dcs.length === 0}
            onChange={e => onChange({ ...value, datacenter: e.target.value, clusters: [], hosts: [] })}>
            <option value="">{t('vi_scope_all')}</option>
            {dcs.map(d => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">{t('vi_scope_cluster')}
          {multi(cls, value.clusters, v => onChange({ ...value, clusters: v, hosts: [] }), 'scope-clusters')}
        </label>
        {showHosts && (
          <label className="flex flex-col gap-1 text-xs text-slate-400">{t('vi_scope_host')}
            {multi(hosts, value.hosts, v => onChange({ ...value, hosts: v }), 'scope-hosts')}
          </label>
        )}
      </div>
      <div className="text-[11px] text-slate-500 inline-flex items-center">{t('vi_scope_all_hint')}<TermHint k="scope" /></div>
    </div>
  )
}

export type Scope = { instance: string; datacenter: string; clusters: string[]; hosts: string[] }
export const EMPTY_SCOPE: Scope = { instance: '', datacenter: '', clusters: [], hosts: [] }

/** Seçili kapsamın özeti parçaları (boşsa seçim yok = tüm ortamlar). */
export function scopeSummaryParts(clusters: Cluster[], value: Scope, t: (k: any, v?: any) => string): string[] {
  const parts: string[] = []
  if (value.instance) {
    const c = clusters.find((x: any) => String(x.hypervisor_id) === value.instance)
    parts.push(c?.hypervisor || value.instance)
  }
  if (value.datacenter) parts.push(value.datacenter)
  if (value.clusters.length) parts.push(t('vi_scope_n_clusters', { n: value.clusters.length }))
  if (value.hosts.length) parts.push(t('vi_scope_n_hosts', { n: value.hosts.length }))
  return parts
}

/** Kapsam seçicisi varsayılan KAPALI: başlıkta özet ("Kapsam: tüm ortamlar" / "2 cluster seçili") + aç/daralt.
 *  Seçim durumu üstte tutulur; daraltmak seçimi silmez. */
export function CollapsibleScope({ clusters, value, onChange, defaultOpen = false, showHosts = true }:
  { clusters: Cluster[]; value: Scope; onChange: (s: Scope) => void; defaultOpen?: boolean; showHosts?: boolean }) {
  const t = useT()
  const [open, setOpen] = useState(defaultOpen)
  const parts = scopeSummaryParts(clusters, value, t)
  const summary = parts.length ? parts.join(' · ') : t('vi_scope_sum_all')
  // Seçimler tek tek kaldırılabilir çip olarak gösterilir (× ile o seçim silinir; üst seviye silinince altındakiler de temizlenir).
  const chips: { key: string; label: string; remove: () => void }[] = []
  if (value.instance) {
    const c = clusters.find((x: any) => String(x.hypervisor_id) === value.instance)
    chips.push({ key: `inst-${value.instance}`, label: c?.hypervisor || value.instance, remove: () => onChange({ ...EMPTY_SCOPE }) })
  }
  if (value.datacenter) chips.push({ key: `dc-${value.datacenter}`, label: value.datacenter, remove: () => onChange({ ...value, datacenter: '', clusters: [], hosts: [] }) })
  value.clusters.forEach(cl => chips.push({ key: `cl-${cl}`, label: cl, remove: () => onChange({ ...value, clusters: value.clusters.filter(x => x !== cl), hosts: [] }) }))
  if (showHosts) value.hosts.forEach(h => chips.push({ key: `h-${h}`, label: h, remove: () => onChange({ ...value, hosts: value.hosts.filter(x => x !== h) }) }))
  return (
    <div className="rounded border border-white/[0.06]" data-testid="scope-collapsible">
      <div className="flex items-center gap-2 px-3 py-2 text-xs">
        <button type="button" data-testid="scope-toggle" aria-expanded={open} onClick={() => setOpen(o => !o)}
          className="inline-flex items-center gap-1.5 text-slate-300 hover:text-white">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span data-testid="scope-summary">{t('vi_scope_label')}: {summary}</span>
          <span className="text-blue-300">— {open ? t('vi_scope_collapse') : t('vi_scope_expand')}</span>
        </button>
      </div>
      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 px-3 pb-2" data-testid="scope-chips">
          {chips.map(c => (
            <span key={c.key} className="inline-flex items-center gap-1 rounded-full border border-blue-500/40 bg-blue-600/10 px-2 py-0.5 text-[11px] text-blue-200">
              {c.label}
              <button type="button" aria-label={`${t('vi_scope_remove')}: ${c.label}`} data-testid={`scope-chip-x-${c.key}`} onClick={c.remove}
                className="text-blue-300 hover:text-white leading-none">×</button>
            </span>
          ))}
        </div>
      )}
      {open && (
        <div className="px-3 pb-3 space-y-2" data-testid="scope-body">
          <ScopeSelect clusters={clusters} value={value} onChange={onChange} showHosts={showHosts} />
          {showHosts && (
            <div className="text-[11px] text-slate-500 inline-flex items-center" data-testid="scope-host-note">
              {t('vi_scope_host_note')}<TermHint k="scope_host" />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const PLATFORM_LABEL: Record<string, string> = { vmware: 'VMware', olvm: 'OLVM', ocp_virt: 'OpenShift Virtualization' }

/** Platform çipleri: yalnız ortamda gerçekten bulunan platformlardan türetilir (uydurma etiket yok). Boş seçim = hepsi. */
export function PlatformChips({ clusters, value, onChange }: { clusters: Cluster[]; value: string[]; onChange: (v: string[]) => void }) {
  const t = useT()
  const present = Array.from(new Set(clusters.map((c: any) => c.platform).filter(Boolean))) as string[]
  if (present.length < 2) return null           // tek platform varsa seçim anlamsız
  const toggle = (p: string) => onChange(value.includes(p) ? value.filter(x => x !== p) : [...value, p])
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="platform-chips">
      <span className="text-xs text-slate-400 inline-flex items-center">{t('vi_wi_platforms')}<TermHint k="platform" /></span>
      {present.map(p => (
        <button key={p} type="button" data-testid={`platform-${p}`} aria-pressed={value.includes(p)} onClick={() => toggle(p)}
          className={`rounded-full border px-2.5 py-0.5 text-xs ${value.includes(p)
            ? 'border-blue-500/60 bg-blue-600/20 text-blue-200' : 'border-white/[0.1] text-slate-400 hover:text-slate-200'}`}>
          {PLATFORM_LABEL[p] || p}
        </button>
      ))}
      <span className="text-[11px] text-slate-500">{value.length ? '' : t('vi_wi_platforms_all')}</span>
    </div>
  )
}

function WhatIf({ clusters }: { clusters: Cluster[] }) {
  const t = useT()
  const [platforms, setPlatforms] = useState<string[]>([])
  const [vcpu, setVcpu] = useState('8')
  const [mem, setMem] = useState('32')
  const [disk, setDisk] = useState('100')
  const [count, setCount] = useState('1')
  const [scope, setScope] = useState<Scope>(EMPTY_SCOPE)
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState('')
  const [cloned, setCloned] = useState<VmOpt | null>(null)
  const run = async () => {
    setErr('')
    try {
      const body: any = { vcpu: Number(vcpu), memory_gb: Number(mem), disk_gb: Number(disk), count: Number(count) }
      if (scope.instance) body.hypervisor_id = Number(scope.instance)
      if (scope.datacenter) body.datacenter = scope.datacenter
      if (scope.clusters.length) body.clusters = scope.clusters
      if (platforms.length) body.platforms = platforms        // F2: bu ekranda host seçici yok (host daraltması Toplu yerleşim'de)
      setRes(await apiSend('virt-insights', '/capacity/simulate', 'POST', body))
    } catch (e: any) { setErr(e.message) }
  }
  return (
    <Panel title={t('vi_whatif_title')} method="cap.sim.add_vms">
      <div className="p-4 space-y-4">
        <PlatformChips clusters={clusters} value={platforms} onChange={setPlatforms} />
        <CollapsibleScope clusters={clusters} value={scope} onChange={setScope} showHosts={false} />
        <div className="flex flex-wrap items-end gap-3">
          <VmPicker label={t('vi_whatif_clone')} placeholder={t('vi_whatif_clone_ph')} listId="vi-whatif-vm-list"
            onPick={vm => {
              setCloned(vm)
              if (vm) {
                setVcpu(String(vm.vcpu || 1)); setMem(String(vm.memory_gb ?? 0)); setDisk(String(Math.round(vm.disk_gb || 0)))
              }
            }} />
          <span className="text-xs text-slate-500 pb-2">{t('vi_or')}</span>
          <Num label="vCPU" value={vcpu} onChange={setVcpu} hint="vcpu" />
          <Num label="Memory (GB)" value={mem} onChange={setMem} hint="memory" />
          <Num label="Disk (GB)" value={disk} onChange={setDisk} hint="disk" />
          <Num label={t('vi_whatif_count')} value={count} onChange={setCount} hint="count" />
          <GhostButton accent={NEON.blue} onClick={run}>{t('vi_whatif_run')}</GhostButton>
        </div>
        {cloned && <div className="text-[11px] text-blue-300">{t('vi_whatif_cloned', { name: cloned.name, vcpu: cloned.vcpu ?? 0, mem: cloned.memory_gb ?? 0, disk: Math.round(cloned.disk_gb || 0) })}</div>}
        {err && <div className="text-red-300 text-xs">{err}</div>}
        {res && (
          <>
            <WhatIfResults results={res.results || []} count={Number(res.request?.count ?? 1)} assumptions={res.assumptions} />
          </>
        )}
      </div>
    </Panel>
  )
}

/** Toplu yerleşim için kapsam (instance/DC/cluster/host + platform) burada tutulur; formu BulkPlacement çizer. */
function BulkTab({ clusters }: { clusters: Cluster[] }) {
  const [platforms, setPlatforms] = useState<string[]>([])
  const [scope, setScope] = useState<Scope>(EMPTY_SCOPE)
  const scopeBody = () => {
    const b: Record<string, unknown> = {}
    if (scope.instance) b.hypervisor_id = Number(scope.instance)
    if (scope.datacenter) b.datacenter = scope.datacenter
    if (scope.clusters.length) b.clusters = scope.clusters
    if (scope.hosts.length) b.hosts = scope.hosts
    if (platforms.length) b.platforms = platforms
    return b
  }
  return (
    <BulkPlacement scopeBody={scopeBody} scopeNode={<>
      <PlatformChips clusters={clusters} value={platforms} onChange={setPlatforms} />
      <CollapsibleScope clusters={clusters} value={scope} onChange={setScope} />
    </>} />
  )
}

function Placement() {
  const t = useT()
  const [vm, setVm] = useState<VmOpt | null>(null)
  const [vcpu, setVcpu] = useState('4')
  const [mem, setMem] = useState('16')
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState('')
  const run = async () => {
    setErr('')
    try {
      const body = vm ? { vm_name: vm.name } : { vcpu: Number(vcpu), memory_gb: Number(mem) }
      setRes(await apiSend('virt-insights', '/placement', 'POST', body))
    } catch (e: any) { setErr(e.message) }
  }
  return (
    <Panel title={t('vi_place_title')} method="cap.placement">
      <div className="p-4 space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <VmPicker label={t('vi_place_vm')} placeholder={t('vi_place_vm_ph')} listId="vi-place-vm-list" onPick={setVm} />
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

function PolicyPanel({ onSaved, clusters }: { onSaved: () => void; clusters: Cluster[] }) {
  const t = useT()
  const [spec, setSpec] = useState<Record<string, any>>({})
  const [vals, setVals] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const load = async () => {
    const r = await apiGet<any>('virt-insights', '/capacity/policy')
    setSpec(r.spec || {})
    setVals(Object.fromEntries(Object.entries(r.values || {}).map(([k, v]) => [k, String(v)])))
  }
  useEffect(() => { load().catch(e => setMsg({ ok: false, text: e.message })) }, [])
  const save = async () => {
    setMsg(null)
    try {
      const r = await apiSend<any>('virt-insights', '/capacity/policy', 'PUT',
        { values: Object.fromEntries(Object.entries(vals).map(([k, v]) => [k, Number(v)])) })
      setSpec(r.spec || {})
      setMsg({ ok: true, text: t('vi_policy_saved') })
      onSaved()
    } catch (e: any) { setMsg({ ok: false, text: e.message }) }
  }
  const reset = () => setVals(Object.fromEntries(Object.entries(spec).map(([k, s]: any) => [k, String(s.default)])))
  return (
    <Panel title={t('vi_policy_title')} method="cap.policy">
      <div className="p-4 space-y-4">
        <div className="text-xs text-slate-400">{t('vi_policy_intro')}</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {Object.entries(spec).map(([k, s]: any) => (
            <label key={k} className="flex flex-col gap-1 text-xs text-slate-400" data-testid={`policy-${k}`}>
              <span className="text-slate-200 flex items-center">{s.label}<InfoDot label={s.label} text={t(('vi_policy_help_' + k) as any)} />{s.overridden && <span className="ml-2 text-amber-300">{t('vi_policy_changed', { d: s.default })}</span>}</span>
              <input type="number" min={s.min} max={s.max} step="1" value={vals[k] ?? ''}
                onChange={e => setVals(v => ({ ...v, [k]: e.target.value }))}
                className="w-32 rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white font-mono" />
              <span className="text-slate-500">{t('vi_policy_range', { a: s.min, b: s.max, d: s.default })}</span>
            </label>
          ))}
        </div>
        <div className="flex gap-2">
          <GhostButton accent={NEON.blue} onClick={save}>{t('vi_policy_save')}</GhostButton>
          <GhostButton accent={NEON.blue} onClick={reset}>{t('vi_policy_reset')}</GhostButton>
        </div>
        {msg && <div className={`text-xs ${msg.ok ? 'text-emerald-300' : 'text-red-300'}`}>{msg.text}</div>}
        <div className="text-[11px] text-slate-500">{t('vi_policy_note')}</div>
      </div>
      <PolicyOverrides clusters={clusters} />
    </Panel>
  )
}

export default function VirtCapacity() {
  const t = useT()
  // Bulgular → N+1 derin bağlantısı: /virt/capacity?tab=hostfail&hv=<id>&cluster=<ad>&host=<ad>
  const qp = useMemo(() => new URLSearchParams(window.location.search), [])
  const [tab, setTab] = useState(qp.get('tab') || 'clusters')
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
        <Stat label={t('vi_cap_clusters')} value={clusters.length} method="cap.cluster.effective" methodAt={q.data?.as_of} />
        <Stat label={t('vi_cap_n1_broken')} value={n1Fail} tone={n1Fail ? 'text-red-400' : 'text-emerald-400'} method="cap.cluster.n_plus_one" methodAt={q.data?.as_of} />
        <Stat label={t('vi_cap_hosts_needed')} value={hostsNeeded} tone={hostsNeeded ? 'text-amber-400' : 'text-white'} method="cap.actions" methodAt={q.data?.as_of} />
        <Stat label={t('vi_cap_ds_hot')} value={dsHot} tone={dsHot ? 'text-amber-400' : 'text-white'} method="cap.datastore.usage" methodAt={q.data?.as_of} />
      </div>
      <Tabs active={tab} onChange={setTab} tabs={[
        { id: 'clusters', label: 'Cluster', count: clusters.length },
        { id: 'datastores', label: 'Datastore', count: ds.length },
        { id: 'whatif', label: t('vi_whatif_tab') },
        { id: 'hostfail', label: t('vi_hf_tab') },
        { id: 'reclaim', label: t('vi_rc_tab') },
        { id: 'bulk', label: t('vi_bp_tab') },
        { id: 'placement', label: t('vi_place_tab') },
        { id: 'policy', label: t('vi_policy_tab') },
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
            { key: 'usage_pct', label: <span className="inline-flex items-center gap-1">{t('vi_col_usage')}<MethodBadge id="cap.datastore.usage" at={q.data?.as_of} /></span>, render: r => <div className="w-32"><div className={`font-mono text-xs ${pctTone(r.usage_pct, 80, 90)}`}>%{fmt(r.usage_pct)}</div><Bar pct={r.usage_pct} warn={80} crit={90} /></div> },
            { key: 'free_gb', label: t('vi_col_free_gb'), render: r => <span className="font-mono">{fmt(r.free_gb)}</span> },
            { key: 'provisioned_pct', label: 'Provisioned %', render: r => <span className={`font-mono ${pctTone(r.provisioned_pct, 100, 150)}`}>{fmt(r.provisioned_pct)}</span> },
            { key: 'runway', label: <span className="inline-flex items-center gap-1">{t('vi_cap_runway')}<MethodBadge id="cap.datastore.runway" at={q.data?.as_of} /></span>, render: r => runwayTxt(r.forecast, t) },
          ]} />
        </Panel>
      )}
      {tab === 'whatif' && <WhatIf clusters={clusters} />}
      {tab === 'hostfail' && <Panel title={t('vi_hf_tab')} method="cap.sim.host_failure"><HostFailure clusters={clusters} initialKey={qp.get('hv') && qp.get('cluster') ? `${qp.get('hv')}:${qp.get('cluster')}` : undefined} initialHost={qp.get('host') || undefined} /></Panel>}
      {tab === 'reclaim' && <Panel title={t('vi_rc_title')} method="cap.sim.reclaim"><ReclaimSim clusters={clusters} /></Panel>}
      {tab === 'bulk' && <Panel title={t('vi_bp_title')} method="cap.sim.bulk_placement"><BulkTab clusters={clusters} /></Panel>}
      {tab === 'placement' && <Placement />}
      {tab === 'policy' && <PolicyPanel onSaved={() => q.refetch?.()} clusters={clusters} />}
    </div>
  )
}
