/**
 * Sanallaştırma Komuta Merkezi — vCenter, OLVM/oVirt, ESX host kaynakları ve platform logları
 */
import { useState, useMemo, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Search, X, Cpu, MemoryStick, HardDrive, Server, Cloud,
  AlertTriangle, CheckCircle2, ScrollText, Database,
  Activity, ChevronRight, Layers,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { OpsRefreshCountdown, OpsShell } from '../components/ops/OpsShell'

interface PlatformCard {
  id: number; name: string; type: string; platform: string
  hostname: string; ip_address: string; port: number
  host_count: number; vm_total: number; vm_running: number; vm_offline: number
  avg_cpu_pct: number; avg_mem_pct: number; avg_disk_pct: number
  last_metric_at: string | null; status: string
  issues: { severity: string; title: string; detail?: string }[]
}

interface HostAlert {
  alert_type?: 'host' | 'platform'
  hypervisor_id: number; hypervisor_name: string; platform: string
  host_name: string; max_severity: string
  cpu_usage_pct: number; mem_usage_pct: number; ds_usage_pct: number
  vms_running: number; vms_total: number
  connection_state?: string; maintenance_mode: boolean
  last_updated: string | null
  issues: { severity: string; category: string; title: string; detail?: string; value?: number }[]
  suggested_actions: string[]
}

interface PlatformLog {
  id: string | number; source: string; severity: string
  source_label?: string
  category?: string; action?: string; title: string
  detail?: string; actor?: string; status?: string
  platform?: string; host_name?: string; timestamp: string | null
}

interface VirtOpsData {
  health: { score: number; grade: string; label: string; color: string }
  totals: {
    hypervisor_count: number; host_count: number
    vm_total: number; vm_running: number
    avg_cpu_pct: number; avg_mem_pct: number
  }
  platforms: PlatformCard[]
  critical_hosts: HostAlert[]
  warning_hosts: HostAlert[]
  critical_count: number
  warning_count: number
  critical_host_count?: number
  critical_platform_count?: number
  warning_host_count?: number
  warning_platform_count?: number
  platform_logs: PlatformLog[]
  generated_at: string
}

const SEV_BADGE: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-300 border-red-500/40',
  warning: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
  info: 'bg-blue-500/20 text-blue-300 border-blue-500/40',
  ok: 'bg-green-500/20 text-green-300 border-green-500/40',
}

const PLATFORM_COLOR: Record<string, string> = {
  vmware: 'from-green-600/20 to-emerald-600/10 border-green-500/30',
  kvm: 'from-orange-600/20 to-amber-600/10 border-orange-500/30',
  hyperv: 'from-blue-600/20 to-cyan-600/10 border-blue-500/30',
  proxmox: 'from-red-600/20 to-orange-600/10 border-red-500/30',
}

function relTime(iso: string | null): string {
  if (!iso) return '—'
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (m < 1) return 'şimdi'
  if (m < 60) return `${m}dk`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}s`
  return `${Math.floor(h / 24)}g`
}

function ResourceBar({ label, pct, icon }: { label: string; pct: number; icon: React.ReactNode }) {
  const color = pct >= 90 ? 'bg-red-500' : pct >= 75 ? 'bg-amber-500' : pct >= 50 ? 'bg-blue-500' : 'bg-green-500'
  const safe = Math.min(100, Math.max(0, Number(pct) || 0))
  return (
    <div className="min-w-0 w-full">
      <div className="flex items-center justify-between text-xs mb-1 gap-2">
        <span className="text-slate-400 flex items-center gap-1 truncate">{icon}<span className="truncate">{label}</span></span>
        <span className="text-slate-300 font-medium flex-shrink-0">%{safe.toFixed(0)}</span>
      </div>
      <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden w-full">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${safe}%` }} />
      </div>
    </div>
  )
}

function PlatformManagerCard({ p }: { p: PlatformCard }) {
  const style = PLATFORM_COLOR[p.type] || 'from-slate-600/20 to-slate-700/10 border-slate-600/30'
  return (
    <div className={`rounded-xl border bg-gradient-to-br p-4 w-[min(100%,320px)] min-w-[280px] flex-shrink-0 ${style}`}>
      <div className="flex items-start justify-between mb-3 gap-2">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-lg bg-slate-900/50 flex items-center justify-center flex-shrink-0">
            <Cloud size={18} className="text-white" />
          </div>
          <div className="min-w-0">
            <div className="text-white font-semibold truncate">{p.name}</div>
            <div className="text-xs text-slate-400 truncate">{p.platform} · {p.ip_address}:{p.port}</div>
          </div>
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold uppercase flex-shrink-0 ${SEV_BADGE[p.status] || SEV_BADGE.ok}`}>
          {p.status === 'ok' ? 'OK' : p.status}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 mb-3 text-center">
        <div className="bg-slate-900/40 rounded-lg py-2 px-1">
          <div className="text-lg font-bold text-white">{p.host_count}</div>
          <div className="text-[10px] text-slate-500">Host</div>
        </div>
        <div className="bg-slate-900/40 rounded-lg py-2 px-1">
          <div className="text-lg font-bold text-green-400">{p.vm_running}</div>
          <div className="text-[10px] text-slate-500">VM Aktif</div>
        </div>
        <div className="bg-slate-900/40 rounded-lg py-2 px-1">
          <div className="text-lg font-bold text-slate-400">{p.vm_offline}</div>
          <div className="text-[10px] text-slate-500">VM Kapalı</div>
        </div>
      </div>
      <div className="space-y-2.5">
        <ResourceBar label="CPU" pct={p.avg_cpu_pct} icon={<Cpu size={11} />} />
        <ResourceBar label="RAM" pct={p.avg_mem_pct} icon={<MemoryStick size={11} />} />
        <ResourceBar label="Disk" pct={p.avg_disk_pct} icon={<HardDrive size={11} />} />
      </div>
      {p.last_metric_at && (
        <div className="text-[10px] text-slate-500 mt-2">Son metrik: {relTime(p.last_metric_at)} önce</div>
      )}
      {p.issues.length > 0 && (
        <div className="mt-3 pt-3 border-t border-white/10 space-y-1">
          {p.issues.slice(0, 2).map((i, idx) => (
            <div key={idx} className="text-xs text-amber-300 flex items-center gap-1.5 min-w-0">
              <AlertTriangle size={11} className="flex-shrink-0" /> <span className="truncate">{i.title}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function HostAlertCard({ host, onSelect, selected }: {
  host: HostAlert; onSelect: () => void; selected: boolean
}) {
  const sev = host.max_severity
  const isPlatform = host.alert_type === 'platform'
  return (
    <button
      onClick={onSelect}
      className={`w-full text-left rounded-xl border p-4 transition-all hover:border-slate-500 ${
        selected ? 'border-cyan-500/50 bg-cyan-500/5' :
        sev === 'critical' ? 'border-red-500/30 bg-red-500/5' : 'border-amber-500/25 bg-amber-500/5'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-bold ${SEV_BADGE[sev]}`}>
              {sev.toUpperCase()}
            </span>
            {isPlatform ? (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/30">
                Yönetim Platformu
              </span>
            ) : (
              <span className="text-[10px] text-slate-500">{host.platform}</span>
            )}
          </div>
          <div className="text-white font-semibold mt-1 truncate flex items-center gap-1.5">
            {isPlatform && <Cloud size={14} className="text-cyan-400 shrink-0" />}
            {host.host_name}
          </div>
          <div className="text-xs text-slate-500 truncate">
            {isPlatform
              ? `${host.platform} · ${host.vms_running}/${host.vms_total} VM`
              : `${host.hypervisor_name} · ${host.vms_running}/${host.vms_total} VM`}
          </div>
        </div>
      </div>
      {!isPlatform && (
        <div className="grid grid-cols-3 gap-3 mt-3">
          <ResourceBar label="CPU" pct={host.cpu_usage_pct} icon={<Cpu size={11} />} />
          <ResourceBar label="RAM" pct={host.mem_usage_pct} icon={<MemoryStick size={11} />} />
          <ResourceBar label="Disk" pct={host.ds_usage_pct} icon={<HardDrive size={11} />} />
        </div>
      )}
      <div className="flex flex-wrap gap-1 mt-2">
        {host.issues.slice(0, 4).map((i, idx) => (
          <span key={idx} className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 max-w-full truncate">
            {i.title}
          </span>
        ))}
      </div>
    </button>
  )
}

function LogTimeline({ logs }: { logs: PlatformLog[] }) {
  if (logs.length === 0) {
    return (
      <div className="text-center py-12 text-slate-500 text-sm">
        Son 24 saatte platform log kaydı yok
      </div>
    )
  }
  return (
    <div className="space-y-2">
      {logs.map(log => (
        <div key={log.id} className="flex gap-3 p-3 rounded-lg bg-slate-800/40 border border-slate-700/40 hover:border-slate-600/50 transition-colors">
          <div className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
            log.severity === 'critical' ? 'bg-red-400' :
            log.severity === 'warning' ? 'bg-amber-400' : 'bg-blue-400'
          }`} />
          <div className="min-w-0 flex-1">
            <div className="text-sm text-slate-200 leading-snug break-words">{log.title}</div>
            <div className="flex flex-wrap gap-2 mt-1 text-[10px] text-slate-500">
              <span>{
                log.source_label
                || (log.source === 'audit' ? 'Audit'
                  : log.source === 'resource_monitor' ? 'Kaynak Mon.'
                  : log.source?.startsWith('vcenter_') ? 'vCenter'
                  : log.source)
              }</span>
              {log.platform && <span>{log.platform}</span>}
              {log.host_name && <span>{log.host_name}</span>}
              {log.actor && <span>{log.actor}</span>}
              <span>{relTime(log.timestamp)}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default function VirtOpsCenter() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [sevFilter, setSevFilter] = useState<'all' | 'critical' | 'warning'>('all')
  const [selectedHost, setSelectedHost] = useState<HostAlert | null>(null)

  const { data, isLoading, refetch, isFetching } = useQuery<VirtOpsData>({
    queryKey: ['virt-ops-center'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/ops/command-center`)
      if (!r.ok) throw new Error('Komuta merkezi verisi alınamadı')
      return r.json()
    },
    refetchInterval: 30_000,
    staleTime: 15_000,
  })

  const allHosts = useMemo(() => [
    ...(data?.critical_hosts || []),
    ...(data?.warning_hosts || []),
  ], [data])

  const filteredHosts = useMemo(() => {
    let list = allHosts
    if (sevFilter === 'critical') list = list.filter(h => h.max_severity === 'critical')
    if (sevFilter === 'warning') list = list.filter(h => h.max_severity === 'warning')
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(h =>
        h.host_name.toLowerCase().includes(q) ||
        h.hypervisor_name.toLowerCase().includes(q) ||
        h.platform.toLowerCase().includes(q)
      )
    }
    return list
  }, [allHosts, sevFilter, search])

  const filteredLogs = useMemo(() => {
    if (!data?.platform_logs) return []
    if (!search.trim()) return data.platform_logs
    const q = search.toLowerCase()
    return data.platform_logs.filter(l =>
      l.title.toLowerCase().includes(q) ||
      (l.detail || '').toLowerCase().includes(q) ||
      (l.host_name || '').toLowerCase().includes(q)
    )
  }, [data?.platform_logs, search])

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['virt-ops-center'] })
    queryClient.invalidateQueries({ queryKey: ['virt-ops-summary'] })
  }, [queryClient])

  const allOk = (data?.critical_count ?? 0) === 0 && (data?.warning_count ?? 0) === 0

  return (
    <div className="-m-5 flex flex-col h-[calc(100vh-3.5rem)] min-h-0 overflow-hidden">
      <OpsShell
        platform="virt"
        loading={isLoading}
        loadingLabel="Sanallaştırma durumu yükleniyor…"
        health={data?.health ? { score: data.health.score, label: data.health.label } : null}
        healthSubtitle="Sanallaştırma sağlığı"
        kpi={{
          critical: data?.critical_count ?? 0,
          warning: data?.warning_count ?? 0,
          tertiaryValue: data?.totals.vm_running ?? 0,
          tertiaryLabel: 'VM Aktif',
        }}
        metaRow={data ? (
          <div className="flex gap-3 text-xs text-slate-400 flex-wrap">
            <span><Database size={12} className="inline mr-1" />{data.totals.hypervisor_count} manager</span>
            <span><Server size={12} className="inline mr-1" />{data.totals.host_count} host</span>
            <span><Cpu size={12} className="inline mr-1" />CPU %{data.totals.avg_cpu_pct}</span>
            <span><MemoryStick size={12} className="inline mr-1" />RAM %{data.totals.avg_mem_pct}</span>
          </div>
        ) : null}
        headerActions={(
          <>
            <Link to="/hypervisors" className="text-xs px-3 py-1.5 rounded-lg border border-slate-700 text-slate-400 hover:text-white hover:border-slate-500 transition-colors flex items-center gap-1">
              <Layers size={12} /> Dashboard
            </Link>
            <Link to="/infra-reports" className="text-xs px-3 py-1.5 rounded-lg border border-slate-700 text-slate-400 hover:text-white hover:border-slate-500 transition-colors flex items-center gap-1">
              <Activity size={12} /> Altyapı Raporları
            </Link>
            <button
              type="button"
              onClick={async () => {
                try {
                  const r = await fetch(`${API_BASE_URL}/hypervisors/sync-vcenter-events`, { method: 'POST' })
                  if (!r.ok) throw new Error(`HTTP ${r.status}`)
                  await refetch()
                  invalidate()
                } catch (e) {
                  alert('vCenter event sync hatası: ' + e)
                }
              }}
              disabled={isFetching}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:text-white transition-colors disabled:opacity-50"
            >
              <ScrollText size={12} />
              vCenter Sync
            </button>
            <OpsRefreshCountdown onRefresh={() => { refetch(); invalidate() }} interval={30} />
          </>
        )}
        filterBar={(
          <>
            <div className="relative flex-1 min-w-[12rem] max-w-md">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Host, platform veya log ara…"
                className="w-full bg-slate-800 border border-slate-700 text-white text-sm rounded-xl pl-9 pr-8 py-2 focus:outline-none focus:ring-2 focus:ring-cyan-500/50"
              />
              {search && (
                <button type="button" onClick={() => setSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white">
                  <X size={13} />
                </button>
              )}
            </div>
            {(['all', 'critical', 'warning'] as const).map(s => (
              <button
                key={s}
                type="button"
                onClick={() => setSevFilter(s)}
                className={`text-xs px-3 py-1.5 rounded-xl border transition-colors ${
                  sevFilter === s ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-300' : 'border-slate-700 text-slate-500 hover:text-slate-300'
                }`}
              >
                {s === 'all' ? 'Tümü' : s === 'critical' ? 'Kritik' : 'Uyarı'}
              </button>
            ))}
          </>
        )}
        sideRail={(
          <div className="h-full min-h-0 overflow-y-auto px-4 py-4 bg-slate-900/30">
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3 flex items-center gap-2 sticky top-0 bg-slate-900/95 py-2 -mt-2 z-10">
              <ScrollText size={13} className="flex-shrink-0" />
              <span className="truncate">Platform Logları (24s)</span>
            </h2>
            <LogTimeline logs={filteredLogs} />
          </div>
        )}
      >
        {data && data.platforms.length > 0 && (
          <section>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-2">
              <Cloud size={13} /> Yönetim Platformları
            </h2>
            <div className="flex gap-4 overflow-x-auto pb-1 -mx-1 px-1 scrollbar-thin">
              {data.platforms.map(p => <PlatformManagerCard key={p.id} p={p} />)}
            </div>
          </section>
        )}

        {allOk && !search && sevFilter === 'all' ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <CheckCircle2 size={48} className="text-green-400 mb-4" />
            <h3 className="text-lg font-semibold text-green-400">Sanallaştırma katmanı sağlıklı</h3>
            <p className="text-sm text-slate-400 mt-2">Host kaynak ve platform uyarısı yok.</p>
          </div>
        ) : (
          <>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3 flex items-center gap-2">
              <Server size={13} /> Aktif Uyarılar ({filteredHosts.length})
            </h2>
            <div className="space-y-3 max-w-4xl">
              {filteredHosts.map(h => (
                <HostAlertCard
                  key={`${h.alert_type || 'host'}-${h.hypervisor_id}-${h.host_name}`}
                  host={h}
                  selected={
                    selectedHost?.host_name === h.host_name
                    && selectedHost?.hypervisor_id === h.hypervisor_id
                    && (selectedHost?.alert_type || 'host') === (h.alert_type || 'host')
                  }
                  onSelect={() => setSelectedHost(prev =>
                    prev?.host_name === h.host_name
                    && prev?.hypervisor_id === h.hypervisor_id
                    && (prev?.alert_type || 'host') === (h.alert_type || 'host')
                      ? null : h
                  )}
                />
              ))}
              {filteredHosts.length === 0 && (
                <p className="text-sm text-slate-500 text-center py-8">Filtreye uygun host uyarısı yok</p>
              )}
            </div>
          </>
        )}

        {selectedHost && (
          <div className="mt-2 p-4 rounded-xl border border-cyan-500/30 bg-cyan-500/5 max-w-4xl">
            <h3 className="text-sm font-semibold text-cyan-300 mb-3 truncate">{selectedHost.host_name} — Detay</h3>
            <div className="space-y-2 mb-4">
              {selectedHost.issues.map((i, idx) => (
                <div key={idx} className="flex items-center gap-2 text-sm min-w-0">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded border flex-shrink-0 ${SEV_BADGE[i.severity]}`}>{i.severity}</span>
                  <span className="text-slate-300 truncate">{i.title}</span>
                </div>
              ))}
            </div>
            <div className="text-xs text-slate-500 uppercase tracking-wider mb-2">Önerilen Aksiyonlar</div>
            <ul className="space-y-1">
              {selectedHost.suggested_actions.map((a, i) => (
                <li key={i} className="text-xs text-slate-400 flex gap-2">
                  <ChevronRight size={12} className="text-cyan-500 shrink-0 mt-0.5" /> {a}
                </li>
              ))}
            </ul>
          </div>
        )}
      </OpsShell>
    </div>
  )
}
