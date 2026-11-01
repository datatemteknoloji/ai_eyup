import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronUp, X } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'
import { virtHostIpHint, virtHostTitle } from '../../lib/virtHostLabel'
import { HealthBadge, WarrantyText } from '../hardware/hwUi'

/**
 * Ana dashboard hiyerarşisi: Hypervisor → ESX host → VM, ve Donanım alarmı → detay.
 * Ortak kural: kart ızgarası 1 sırada 4 kart, ilk görünümde en fazla 2 sıra (8 kart); «Daha fazla» ile bölüm büyür ve
 * kalanlar dikey kaydırılabilir alanda aşağı doğru listelenir. Kart tıklanınca ilgili alt kırılım KARTIN ALTINDA açılır.
 */

export const GRID_COLS = 4
export const GRID_ROWS = 2
export const PAGE_SIZE = GRID_COLS * GRID_ROWS

const C = { blue: '#3b82f6', cyan: '#38bdf8', green: '#22c55e', orange: '#f59e0b', red: '#ef4444' }
const MUTED = 'rgba(148,163,184,0.55)'

// ── Ortak: 4'lü ızgara + «Daha fazla» ───────────────────────────────────────────────────────────────────────────
export function PagedCards<T>({ items, itemKey, render, testId, pageSize = PAGE_SIZE }: {
  items: T[]; itemKey: (x: T) => string; render: (x: T) => React.ReactNode; testId: string; pageSize?: number
}) {
  const t = useT()
  const [expanded, setExpanded] = useState(false)
  const extra = Math.max(0, items.length - pageSize)
  const shown = expanded ? items : items.slice(0, pageSize)
  const grid = (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-2" data-testid={`${testId}-grid`}>
      {shown.map(x => <React.Fragment key={itemKey(x)}>{render(x)}</React.Fragment>)}
    </div>
  )
  return (
    <div data-testid={testId}>
      {expanded ? <div className="max-h-[26rem] overflow-y-auto pr-1" data-testid={`${testId}-scroll`}>{grid}</div> : grid}
      {extra > 0 && (
        <div className="flex justify-center mt-2">
          <button
            type="button"
            data-testid={`${testId}-more`}
            aria-expanded={expanded}
            onClick={() => setExpanded(v => !v)}
            className="inline-flex items-center gap-1 text-xs px-3 py-1 rounded-md border border-white/[0.1] text-slate-300 hover:text-white hover:border-white/[0.25]"
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {expanded ? t('dash_show_less') : t('dash_show_more', { n: extra })}
          </button>
        </div>
      )}
    </div>
  )
}

const pctColor = (p: number) => (p >= 90 ? C.red : p >= 75 ? C.orange : C.blue)

const MiniBar: React.FC<{ label: string; pct: number | null }> = ({ label, pct }) => (
  <div className="min-w-0">
    <div className="flex justify-between text-[9px] text-slate-500 leading-tight">
      <span>{label}</span>
      <span className="tabular-nums">{pct == null ? '—' : `${Math.round(pct)}%`}</span>
    </div>
    <div className="h-1 rounded-full bg-white/[0.06] overflow-hidden mt-0.5">
      <div className="h-full rounded-full" style={{ width: `${Math.min(100, Math.max(0, pct ?? 0))}%`, background: pct == null ? 'transparent' : pctColor(pct) }} />
    </div>
  </div>
)

const cardStyle = (selected: boolean, accent: string): React.CSSProperties => ({
  background: selected ? `${accent}14` : 'rgba(255,255,255,0.03)',
  border: `1px solid ${selected ? accent : 'rgba(255,255,255,0.08)'}`,
})

// ── Host verisi ─────────────────────────────────────────────────────────────────────────────────────────────────
export interface EsxHostLite {
  host_name: string; host_ref?: string; last_updated?: string
  display_name?: string | null; ip_address?: string | null; roles?: string[]
  cpu_usage_pct: number | null; cpu_usage_mhz: number | null; cpu_total_mhz: number | null; cpu_cores: number | null
  mem_used_mb: number | null; mem_total_mb: number | null; mem_usage_pct: number | null
  ds_used_gb: number | null; ds_total_gb: number | null; ds_usage_pct: number | null
  vms_running: number | null; vms_total: number | null
  connection_state: string | null; power_state: string | null; maintenance_mode: number | null
}
export interface HostRow { hvName: string; hypervisor_id: number; host: EsxHostLite }

/** `/hypervisors/host-metrics` (tüm hypervisor'ler, tek istek) — host paneli ve hypervisor ağacı aynı önbelleği paylaşır. */
export function useHostRows(enabled: boolean) {
  return useQuery<HostRow[]>({
    queryKey: ['dash-host-metrics'],
    enabled,
    staleTime: 60_000,
    refetchInterval: 15 * 60 * 1000,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/host-metrics`)
      if (!r.ok) return []
      const d = (await r.json()) as { hosts?: HostRow[] }
      return (d.hosts || []).map(x => ({ hvName: x.hvName, hypervisor_id: x.hypervisor_id, host: x.host }))
    },
  })
}

const hostKey = (r: HostRow) => `${r.hypervisor_id}:${r.host.host_ref || r.host.host_name}`

const pctOf = (pct: number | null, used: number | null, total: number | null) =>
  pct ?? (used != null && total ? (used / total) * 100 : null)

export const hostPcts = (h: EsxHostLite) => ({
  cpu: pctOf(h.cpu_usage_pct, h.cpu_usage_mhz, h.cpu_total_mhz),
  ram: pctOf(h.mem_usage_pct, h.mem_used_mb, h.mem_total_mb),
  dsk: pctOf(h.ds_usage_pct, h.ds_used_gb, h.ds_total_gb),
})

// ── Kompakt host kartı ──────────────────────────────────────────────────────────────────────────────────────────
export const CompactHostCard: React.FC<{ row: HostRow; selected: boolean; onSelect: () => void }> = ({ row, selected, onSelect }) => {
  const t = useT()
  const h = row.host
  const down = h.connection_state === 'disconnected' || h.connection_state === 'notResponding'
  const maint = h.maintenance_mode === 1
  const dot = down ? C.red : maint ? C.orange : C.green
  const p = hostPcts(h)
  const hint = virtHostIpHint(h)
  return (
    <button
      type="button"
      data-testid="host-card"
      aria-pressed={selected}
      title={t('dash_host_click_hint')}
      onClick={onSelect}
      className="text-left rounded-lg p-2.5 transition-colors hover:bg-white/[0.05] min-w-0"
      style={{ ...cardStyle(selected, C.cyan), opacity: down ? 0.65 : 1 }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 min-w-0">
          <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: dot, boxShadow: `0 0 5px ${dot}` }} />
          <span className="text-xs font-semibold text-white truncate">{virtHostTitle(h)}</span>
        </span>
        {h.vms_running != null && (
          <span className="text-[10px] px-1.5 rounded-sm shrink-0" style={{ background: 'rgba(34,211,238,0.08)', color: C.cyan, border: '1px solid rgba(34,211,238,0.2)' }}>
            {h.vms_running}/{h.vms_total ?? '?'} VM
          </span>
        )}
      </div>
      <p className="text-[10px] truncate mt-0.5" style={{ color: MUTED }}>
        {hint ? `${hint} · ${row.hvName}` : row.hvName}{maint ? ` · ${t('dash_maint')}` : ''}
      </p>
      <div className="grid grid-cols-3 gap-2 mt-2">
        <MiniBar label="CPU" pct={p.cpu} />
        <MiniBar label="RAM" pct={p.ram} />
        <MiniBar label="DSK" pct={p.dsk} />
      </div>
    </button>
  )
}

// ── Seçilen host → yalnız o host'un VM'leri ─────────────────────────────────────────────────────────────────────
interface HostVm {
  id: number; name: string; hostname?: string; ip?: string | null; power_state?: string | null; powered_on: boolean
  os?: string | null; cpu?: number | null; memory_gb?: number | null; disk_gb?: number | null
  tools?: string | null; cluster?: string | null; services: string[]
}
interface HostVmsResponse { total: number; running: number; unmapped?: number; vms: HostVm[] }

const Fact: React.FC<{ k: string; v: React.ReactNode }> = ({ k, v }) => (
  <div className="min-w-0">
    <div className="text-[9px] uppercase tracking-wide text-slate-500">{k}</div>
    <div className="text-xs text-slate-100 truncate">{v}</div>
  </div>
)

export const HostVmsPanel: React.FC<{ row: HostRow; onClose: () => void }> = ({ row, onClose }) => {
  const t = useT()
  const h = row.host
  const q = useQuery<HostVmsResponse>({
    queryKey: ['dash-host-vms', row.hypervisor_id, h.host_ref ?? '', h.host_name],
    staleTime: 30_000,
    queryFn: async () => {
      const qs = new URLSearchParams()
      if (h.host_ref) qs.set('host_ref', h.host_ref)
      if (h.host_name) qs.set('host_name', h.host_name)
      const r = await fetch(`${API_BASE_URL}/hypervisors/${row.hypervisor_id}/host-vms?${qs}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    },
  })
  const p = hostPcts(h)
  const fmt = (v: number | null) => (v == null ? '—' : `${Math.round(v)}%`)
  const vms = q.data?.vms ?? []
  return (
    <div className="mt-3 rounded-lg p-3 animate-fade-in" data-testid="host-vms-panel"
      style={{ background: 'rgba(56,189,248,0.04)', border: '1px solid rgba(56,189,248,0.25)' }}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-white truncate">{t('dash_host_vms_title', { host: virtHostTitle(h) })}</h3>
          <p className="text-[11px]" style={{ color: MUTED }}>
            {row.hvName}{q.data ? ` · ${t('dash_host_vms_sum', { n: q.data.total, on: q.data.running })}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Link to="/hypervisors" className="text-[11px]" style={{ color: 'var(--accent)' }}>{t('dash_open_hypervisors')}</Link>
          <button type="button" aria-label={t('dash_close')} data-testid="host-vms-close" onClick={onClose} className="text-slate-400 hover:text-white"><X size={14} /></button>
        </div>
      </div>

      <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mt-3">
        <Fact k="CPU" v={`${fmt(p.cpu)}${h.cpu_cores ? ` · ${h.cpu_cores} ${t('cores')}` : ''}`} />
        <Fact k="RAM" v={`${fmt(p.ram)}${h.mem_total_mb ? ` · ${(h.mem_total_mb / 1024).toFixed(0)} GB` : ''}`} />
        <Fact k="Disk" v={`${fmt(p.dsk)}${h.ds_total_gb ? ` · ${h.ds_total_gb >= 1024 ? `${(h.ds_total_gb / 1024).toFixed(1)} TB` : `${h.ds_total_gb.toFixed(0)} GB`}` : ''}`} />
        <Fact k={t('dash_host_state')} v={h.maintenance_mode === 1 ? t('dash_maint') : (h.connection_state || h.power_state || '—')} />
        <Fact k="IP" v={h.ip_address || virtHostIpHint(h) || '—'} />
        <Fact k={t('dash_updated_short')} v={h.last_updated ? new Date(h.last_updated).toLocaleString() : '—'} />
      </div>

      <div className="mt-3 max-h-64 overflow-auto rounded-sm border border-white/[0.06]">
        {q.isLoading ? (
          <p className="text-xs text-slate-500 p-3">{t('loading')}</p>
        ) : q.isError ? (
          <p className="text-xs text-red-300 p-3">{t('dash_vm_error')}</p>
        ) : !vms.length ? (
          <p className="text-xs text-slate-500 p-3" data-testid="host-vms-empty">
            {(q.data?.unmapped ?? 0) > 0 && (h.vms_total ?? 0) > 0 ? t('dash_vm_unmapped', { n: q.data!.unmapped! }) : t('dash_vm_none')}
          </p>
        ) : (
          <table className="w-full text-left text-xs" data-testid="host-vms-table">
            <thead className="sticky top-0 bg-[#0f172a] text-[10px] uppercase tracking-wide text-slate-500">
              <tr>
                {(['dash_vm_name', 'dash_vm_state', 'dash_vm_ip', 'dash_vm_os', 'dash_vm_cpu', 'dash_vm_mem', 'dash_vm_disk', 'dash_vm_services'] as const)
                  .map(k => <th key={k} className="px-2 py-1.5 font-medium">{t(k)}</th>)}
              </tr>
            </thead>
            <tbody>
              {vms.map(v => (
                <tr key={v.id} className="border-t border-white/[0.04]" data-testid="host-vm-row">
                  <td className="px-2 py-1.5 text-white font-medium">{v.name}</td>
                  <td className="px-2 py-1.5">
                    <span className="inline-flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full" style={{ background: v.powered_on ? C.green : '#64748b' }} />
                      {v.powered_on ? t('dash_vm_on') : (v.power_state || t('dash_vm_off'))}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 font-mono text-slate-300">{v.ip || '—'}</td>
                  <td className="px-2 py-1.5 text-slate-300 max-w-[12rem] truncate" title={v.os || ''}>{v.os || '—'}</td>
                  <td className="px-2 py-1.5 tabular-nums">{v.cpu ?? '—'}</td>
                  <td className="px-2 py-1.5 tabular-nums">{v.memory_gb != null ? `${v.memory_gb} GB` : '—'}</td>
                  <td className="px-2 py-1.5 tabular-nums">{v.disk_gb != null ? `${Math.round(v.disk_gb)} GB` : '—'}</td>
                  <td className="px-2 py-1.5 text-slate-300 max-w-[14rem] truncate" title={v.services.join(', ')}>{v.services.length ? v.services.join(', ') : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── Host ızgarası (kart → VM) ───────────────────────────────────────────────────────────────────────────────────
export const HostsGrid: React.FC<{ rows: HostRow[]; testId: string }> = ({ rows, testId }) => {
  const [sel, setSel] = useState<string | null>(null)
  const selected = rows.find(r => hostKey(r) === sel) || null
  return (
    <>
      <PagedCards
        testId={testId}
        items={rows}
        itemKey={hostKey}
        render={r => <CompactHostCard row={r} selected={hostKey(r) === sel} onSelect={() => setSel(cur => (cur === hostKey(r) ? null : hostKey(r)))} />}
      />
      {selected && <HostVmsPanel row={selected} onClose={() => setSel(null)} />}
    </>
  )
}

// ── Tüm host'lar paneli ─────────────────────────────────────────────────────────────────────────────────────────
export const HostsPanel: React.FC<{ enabled: boolean }> = ({ enabled }) => {
  const t = useT()
  const q = useHostRows(enabled)
  const rows = q.data ?? []
  return (
    <div className="cyber-card" data-testid="hosts-panel">
      <div className="px-5 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
        <div>
          <h2 className="text-sm font-semibold text-white">{t('dash_esx_title')}</h2>
          <p className="text-xs" style={{ color: MUTED }}>{t('dash_esx_sub')}</p>
        </div>
        {q.isLoading ? <span className="text-xs" style={{ color: MUTED }}>{t('loading')}</span>
          : <span className="text-xs text-slate-400">{t('dash_host_count', { n: rows.length })}</span>}
      </div>
      {!rows.length && !q.isLoading ? (
        <div className="px-5 py-10 text-center" style={{ color: 'rgba(148,163,184,0.4)' }}>
          <p className="text-sm">{t('dash_esx_empty')}</p>
          <p className="text-xs mt-1" style={{ color: 'rgba(148,163,184,0.25)' }}>{t('dash_esx_empty_hint')}</p>
        </div>
      ) : (
        <div className="p-4"><HostsGrid rows={rows} testId="hosts" /></div>
      )}
    </div>
  )
}

// ── Hypervisor ağacı: hypervisor → cluster → host → VM ───────────────────────────────────────────────────────────
export interface HypervisorLite { id: number; name: string; type: string; ip_address: string }

const STANDALONE = '__standalone__'

interface HierHost { host_name: string; host_ref?: string | null; state?: string | null; cpu_pct?: number | null; mem_pct?: number | null; vms_total: number; vms_running: number }
interface HierCluster { name: string; standalone: boolean; ha_enabled?: boolean | null; drs_enabled?: boolean | null; host_count: number; vms_total: number; vms_running: number; hosts: HierHost[] }
interface HierHv { hypervisor_id: number; name: string; type: string; host_count: number; vms_total: number; vms_running: number; vms_unmapped: number; clusters: HierCluster[] }

/** VM sayıları `servers` envanterinden (host metriği değil — o toplanınca N kat şişiyordu). */
function useHierarchy(enabled: boolean) {
  return useQuery<{ hypervisors: HierHv[] }>({
    queryKey: ['virt-hierarchy'],
    enabled,
    staleTime: 60_000,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/hierarchy`)
      if (!r.ok) return { hypervisors: [] }
      return r.json()
    },
  })
}

function hvAccent(type: string) {
  const tp = (type || '').toLowerCase()
  if (tp === 'vmware') return { c: C.blue, tag: 'VM' }
  if (tp === 'kvm' || tp.includes('ovirt') || tp.includes('olvm')) return { c: C.orange, tag: 'OV' }
  return { c: C.cyan, tag: 'HV' }
}

export const HypervisorTree: React.FC<{ hypervisors: HypervisorLite[]; hostsEnabled: boolean }> = ({ hypervisors, hostsEnabled }) => {
  const t = useT()
  const hierQ = useHierarchy(hostsEnabled && hypervisors.length > 0)
  const [selHv, setSelHv] = useState<number | null>(null)
  const [selCluster, setSelCluster] = useState<string | null>(null)
  const [selHost, setSelHost] = useState<string | null>(null)
  if (hypervisors.length === 0) return null
  const tree = hierQ.data?.hypervisors ?? []
  const infoOf = (id: number) => tree.find(h => h.hypervisor_id === id)
  const selected = infoOf(selHv ?? -1) || null
  const cluster = selected?.clusters.find(c => c.name === selCluster) || null
  const host = cluster?.hosts.find(h => (h.host_ref || h.host_name) === selHost) || null
  const pickHv = (id: number) => { setSelHv(cur => (cur === id ? null : id)); setSelCluster(null); setSelHost(null) }
  const pickCluster = (name: string) => { setSelCluster(cur => (cur === name ? null : name)); setSelHost(null) }
  return (
    <div className="cyber-card animate-fade-in" data-testid="hypervisor-tree">
      <div className="px-5 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-4 rounded-full" style={{ background: C.blue }} />
          <h2 className="text-sm font-semibold text-white">{t('dash_hypervisors')}</h2>
          <span className="text-xs text-slate-500">{t('dash_hv_tree_hint')}</span>
        </div>
        <Link to="/hypervisors" className="text-xs font-medium" style={{ color: 'var(--accent)' }}>{t('view_all')}</Link>
      </div>
      <div className="p-4">
        <PagedCards
          testId="hypervisors"
          items={hypervisors}
          itemKey={h => String(h.id)}
          render={hv => {
            const a = hvAccent(hv.type)
            const info = infoOf(hv.id)
            const on = selHv === hv.id
            return (
              <button
                type="button"
                data-testid="hypervisor-card"
                aria-pressed={on}
                onClick={() => pickHv(hv.id)}
                className="text-left rounded-lg p-2.5 transition-colors hover:bg-white/[0.05] min-w-0"
                style={cardStyle(on, a.c)}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="w-7 h-7 rounded-md flex items-center justify-center shrink-0 text-[10px] font-bold" style={{ background: `${a.c}1f`, color: a.c }}>{a.tag}</span>
                  <span className="min-w-0">
                    <span className="block text-xs font-semibold text-white truncate">{hv.name}</span>
                    <span className="block text-[10px] truncate" style={{ color: `${a.c}b0` }}>{(hv.type || '').toUpperCase()} · {hv.ip_address}</span>
                  </span>
                </div>
                <div className="flex gap-2 mt-2 text-[10px] text-slate-400">
                  <span>{t('dash_host_count', { n: info?.host_count ?? 0 })}</span>
                  <span>·</span>
                  <span>{t('dash_vm_count', { n: info?.vms_total ?? 0 })}</span>
                </div>
              </button>
            )
          }}
        />
        {selected && (
          <div className="mt-3 rounded-lg p-3 animate-fade-in" data-testid="hypervisor-clusters-panel"
            style={{ background: 'rgba(59,130,246,0.04)', border: '1px solid rgba(59,130,246,0.25)' }}>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-white">{t('dash_hv_clusters_title', { name: selected.name })}</h3>
              <button type="button" aria-label={t('dash_close')} data-testid="hypervisor-clusters-close" onClick={() => pickHv(selected.hypervisor_id)} className="text-slate-400 hover:text-white"><X size={14} /></button>
            </div>
            {hierQ.isLoading ? (
              <p className="text-xs text-slate-500">{t('loading')}</p>
            ) : selected.clusters.length ? (
              <PagedCards
                testId="clusters"
                items={selected.clusters}
                itemKey={c => c.name}
                render={c => {
                  const on = selCluster === c.name
                  return (
                    <button type="button" data-testid="cluster-card" aria-pressed={on} onClick={() => pickCluster(c.name)}
                      className="text-left rounded-lg p-2.5 transition-colors hover:bg-white/[0.05] min-w-0" style={cardStyle(on, C.cyan)}>
                      <span className="block text-xs font-semibold text-white truncate">{c.standalone ? t('dash_cluster_standalone') : c.name}</span>
                      <span className="block text-[10px] text-slate-400 mt-1">
                        {t('dash_host_count', { n: c.host_count })} · {t('dash_vm_count', { n: c.vms_total })}
                        {c.ha_enabled ? ` · HA` : ''}{c.drs_enabled ? ` · DRS` : ''}
                      </span>
                    </button>
                  )
                }}
              />
            ) : (
              <p className="text-xs text-slate-500" data-testid="hypervisor-clusters-empty">{t('dash_hv_no_clusters')}</p>
            )}
            {cluster && (
              <div className="mt-3" data-testid="cluster-hosts-panel">
                <h4 className="text-xs font-semibold text-slate-300 mb-2">{t('dash_cluster_hosts_title', { name: cluster.standalone ? t('dash_cluster_standalone') : cluster.name })}</h4>
                {cluster.hosts.length ? (
                  <PagedCards
                    testId="cluster-hosts"
                    items={cluster.hosts}
                    itemKey={h => h.host_ref || h.host_name}
                    render={h => {
                      const key = h.host_ref || h.host_name
                      const on = selHost === key
                      return (
                        <button type="button" data-testid="cluster-host-card" aria-pressed={on} onClick={() => setSelHost(cur => (cur === key ? null : key))}
                          className="text-left rounded-lg p-2.5 transition-colors hover:bg-white/[0.05] min-w-0" style={cardStyle(on, C.green)}>
                          <span className="block text-xs font-semibold text-white truncate">{h.host_name}</span>
                          <div className="mt-1.5 space-y-1"><MiniBar label="CPU" pct={h.cpu_pct ?? null} /><MiniBar label="RAM" pct={h.mem_pct ?? null} /></div>
                          <span className="block text-[10px] text-slate-400 mt-1">{t('dash_vm_count', { n: h.vms_total })} · {h.vms_running} {t('dash_vm_on')}</span>
                        </button>
                      )
                    }}
                  />
                ) : <p className="text-xs text-slate-500">{t('dash_hv_no_hosts')}</p>}
                {host && (
                  <HostVmsPanel
                    row={{ hvName: selected.name, hypervisor_id: selected.hypervisor_id, host: { host_name: host.host_name, host_ref: host.host_ref || undefined, vms_total: host.vms_total, vms_running: host.vms_running, cpu_usage_pct: host.cpu_pct ?? null, cpu_usage_mhz: null, cpu_total_mhz: null, cpu_cores: null, mem_used_mb: null, mem_total_mb: null, mem_usage_pct: host.mem_pct ?? null, ds_used_gb: null, ds_total_gb: null, ds_usage_pct: null, connection_state: host.state ?? null, power_state: null, maintenance_mode: null } }}
                    onClose={() => setSelHost(null)}
                  />
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Donanım alarmları: kart → detay ─────────────────────────────────────────────────────────────────────────────
interface HwProblem {
  id: number; name: string; vendor?: string | null; model?: string | null; health: string; connected?: boolean | null
  critical_alerts: number; warning_alerts: number; top_alert?: string | null; enclosure?: string | null; bay?: number | null
  target?: { kind?: string; id?: number; name?: string } | null
}
interface HwProblems { enabled: boolean; demo?: boolean; total: number; items: HwProblem[] }

const HW_COLOR: Record<string, string> = { critical: C.red, warning: C.orange, unknown: '#94a3b8', ok: C.green }

const HwDetail: React.FC<{ item: HwProblem; onClose: () => void }> = ({ item, onClose }) => {
  const t = useT()
  const q = useQuery<any>({
    queryKey: ['dash-hw-detail', item.id],
    staleTime: 30_000,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hw/servers/${item.id}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    },
  })
  const d = q.data?.server
  const alerts: any[] = (d?.alerts || []).filter((a: any) => a.state !== 'cleared')
  return (
    <div className="mt-3 rounded-lg p-3 animate-fade-in" data-testid="hw-alarm-detail"
      style={{ background: 'rgba(239,68,68,0.04)', border: '1px solid rgba(239,68,68,0.25)' }}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-white truncate flex items-center gap-2">{item.name} <HealthBadge health={item.health} /></h3>
          <p className="text-[11px]" style={{ color: MUTED }}>{[item.vendor, item.model].filter(Boolean).join(' · ') || '—'}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Link to="/hardware" className="text-[11px]" style={{ color: 'var(--accent)' }}>{t('dash_hw_open')}</Link>
          <button type="button" aria-label={t('dash_close')} data-testid="hw-alarm-close" onClick={onClose} className="text-slate-400 hover:text-white"><X size={14} /></button>
        </div>
      </div>
      {q.isLoading ? <p className="text-xs text-slate-500 mt-2">{t('loading')}</p> : q.isError ? <p className="text-xs text-red-300 mt-2">{t('dash_vm_error')}</p> : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3">
            <Fact k={t('hw_col_enclosure')} v={d?.enclosure_name ? `${d.enclosure_name}${d.bay ? ` / ${d.bay}` : ''}` : '—'} />
            <Fact k={t('hw_col_warranty')} v={<WarrantyText w={d?.warranty ?? null} />} />
            <Fact k={t('hw_col_match')} v={d?.link?.name || '—'} />
            <Fact k={t('dash_hw_alarm_count')} v={`${item.critical_alerts} ${t('hw_health_critical').toLowerCase()} · ${item.warning_alerts} ${t('hw_health_warning').toLowerCase()}`} />
          </div>
          {d?.impact && (d.impact.vm_count > 0 || d.impact.cluster) && (
            <div className="mt-3 rounded-sm border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-100">
              <div className="font-medium">{t('hw_impact_title')}</div>
              <div>{t('hw_impact_vms', { n: d.impact.vm_count, on: d.impact.vm_powered_on })}</div>
              {(d.impact.services || []).length > 0 && <div>{t('hw_impact_services')}: {(d.impact.services as any[]).map(x => `${x.name} (${x.tier})`).join(', ')}</div>}
            </div>
          )}
          <div className="mt-3 max-h-48 overflow-auto rounded-sm border border-white/[0.06]">
            {!alerts.length ? <p className="text-xs text-slate-500 p-3">{t('dash_hw_no_active')}</p> : (
              <ul className="divide-y divide-white/[0.05]" data-testid="hw-alarm-list">
                {alerts.map((a, i) => (
                  <li key={i} className="px-3 py-1.5 text-xs flex gap-2">
                    <span className="mt-1 w-1.5 h-1.5 rounded-full shrink-0" style={{ background: HW_COLOR[a.severity] || '#94a3b8' }} />
                    <span className="min-w-0">
                      <span className="text-slate-100">{a.message}</span>
                      {a.occurred_at && <span className="text-slate-500"> · {new Date(a.occurred_at).toLocaleString()}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export const HwAlarmPanel: React.FC<{ enabled: boolean }> = ({ enabled }) => {
  const t = useT()
  const q = useQuery<HwProblems>({
    queryKey: ['dash-hw-problems'],
    enabled,
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: false,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hw/problem-servers`)
      if (!r.ok) return { enabled: false, total: 0, items: [] }
      return r.json()
    },
  })
  const [sel, setSel] = useState<number | null>(null)
  if (!enabled || !q.data?.enabled) return null
  const items = q.data.items
  const selected = items.find(i => i.id === sel) || null
  const crit = items.filter(i => i.health === 'critical').length
  return (
    <div className="cyber-card animate-fade-in" data-testid="hw-alarm-panel">
      <div className="px-5 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-4 rounded-full" style={{ background: items.length ? (crit ? C.red : C.orange) : C.green }} />
          <h2 className="text-sm font-semibold text-white">{t('dash_hw_title')}</h2>
          {q.data.demo && <span className="text-[10px] px-1.5 rounded-sm border border-fuchsia-500/40 text-fuchsia-300">DEMO</span>}
          <span className="text-xs text-slate-500">{items.length ? t('dash_hw_sub', { n: items.length, c: crit }) : ''}</span>
        </div>
        <Link to="/hardware" className="text-xs font-medium" style={{ color: 'var(--accent)' }}>{t('view_all')}</Link>
      </div>
      <div className="p-4">
        {!items.length ? (
          <p className="text-xs text-emerald-300/80 py-4 text-center" data-testid="hw-alarm-empty">{t('dash_hw_empty')}</p>
        ) : (
          <>
            <PagedCards
              testId="hw-alarms"
              items={items}
              itemKey={i => String(i.id)}
              render={i => {
                const col = HW_COLOR[i.health] || HW_COLOR.unknown
                const on = sel === i.id
                return (
                  <button
                    type="button"
                    data-testid="hw-alarm-card"
                    aria-pressed={on}
                    onClick={() => setSel(cur => (cur === i.id ? null : i.id))}
                    className="text-left rounded-lg p-2.5 transition-colors hover:bg-white/[0.05] min-w-0"
                    style={cardStyle(on, col)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-1.5 min-w-0">
                        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: col, boxShadow: `0 0 5px ${col}` }} />
                        <span className="text-xs font-semibold text-white truncate">{i.name}</span>
                      </span>
                      <span className="flex gap-1 shrink-0 text-[10px]">
                        {i.critical_alerts > 0 && <span className="px-1.5 rounded-sm" style={{ background: 'rgba(239,68,68,0.15)', color: '#fca5a5' }}>{i.critical_alerts}</span>}
                        {i.warning_alerts > 0 && <span className="px-1.5 rounded-sm" style={{ background: 'rgba(245,158,11,0.15)', color: '#fcd34d' }}>{i.warning_alerts}</span>}
                      </span>
                    </div>
                    <p className="text-[10px] truncate mt-0.5" style={{ color: MUTED }}>
                      {[i.vendor, i.model].filter(Boolean).join(' · ') || '—'}{i.target?.name ? ` → ${i.target.name}` : ''}
                    </p>
                    <p className="text-[10px] text-slate-400 mt-1.5 line-clamp-2 min-h-[1.5rem]">{i.top_alert || (i.connected === false ? t('dash_hw_disconnected') : t(`hw_health_${i.health}` as any))}</p>
                  </button>
                )
              }}
            />
            {selected && <HwDetail item={selected} onClose={() => setSel(null)} />}
          </>
        )}
      </div>
    </div>
  )
}
