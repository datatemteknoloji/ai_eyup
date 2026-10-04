/**
 * KubeVirt VM listesi — tablo (sıralama / sayfalama) + OS ikonu + C/M + aksiyonlar.
 * listOnly: özet kartları yok — Linux sunucu listesi tarzı yalnız satırlar.
 */
import React, { useMemo, useState } from 'react'
import {
  ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Loader2,
  Monitor, MonitorPlay, Play, RefreshCw, RotateCcw, Square,
} from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../../config/api'
import { useAuth } from '../../auth/AuthContext'
import OcpVmAdminActions from './OcpVmAdminActions'
import OcpVmDetailDrawer from './OcpVmDetailDrawer'
import { OsIcon } from '../OsIcon'
import { useT } from '../../i18n/LocaleProvider'

type VmRow = {
  name: string
  namespace: string
  phase?: string
  printable_status?: string
  power_state?: string
  ip_address?: string
  node?: string
  node_name?: string
  cpu_count?: number
  cpu_cores?: number
  memory_mb?: number
  memory_gb?: number
  guest_os?: string
  os_type?: string
  usage?: { cpu_millicores?: number; memory_mb?: number } | null
}

type SortKey = 'name' | 'namespace' | 'node' | 'ip' | 'cpu' | 'memory' | 'cpu_pct' | 'mem_pct' | 'status'

const PAGE_SIZE = 25

function openVmConsole(clusterId: number, namespace: string, name: string) {
  const title = encodeURIComponent(`${namespace}/${name}`)
  const url =
    `/openshift/vms/${clusterId}/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/console?title=${title}`
  window.open(url, `ocp-console-${namespace}-${name}`, 'width=1280,height=800')
}

function isRunning(vm: VmRow): boolean {
  return (
    (vm.power_state || '').toLowerCase() === 'poweredon' ||
    (vm.phase || vm.printable_status || '').toLowerCase() === 'running'
  )
}

function UsageBar({ label, pct }: { label: string; pct: number | null }) {
  const t = useT()
  const p = pct == null ? null : Math.max(0, Math.min(100, pct))
  const color =
    p == null ? 'bg-slate-600' : p > 85 ? 'bg-red-500' : p > 70 ? 'bg-amber-500' : 'bg-blue-500'
  return (
    <span className="flex items-center gap-1" title={t('ocp_usage_title', { label })}>
      <span className="text-[9px] text-slate-500 w-3">{label}</span>
      <span className="w-10 h-1 rounded-full bg-slate-700/80 overflow-hidden inline-block">
        <span className={`block h-full rounded-full ${color}`} style={{ width: `${p ?? 0}%` }} />
      </span>
      <span className="text-[9px] text-slate-500 tabular-nums w-7">
        {p == null ? '—' : `%${Math.round(p)}`}
      </span>
    </span>
  )
}

function ipSortKey(ip?: string): number[] {
  const parts = (ip || '').split('.').map((x) => parseInt(x, 10))
  if (parts.length !== 4 || parts.some((n) => Number.isNaN(n))) return [-1]
  return parts
}

type Props = {
  clusterId: number
  /** Özet kartlarını gizle — yalnız VM satır listesi */
  listOnly?: boolean
  search?: string
  statusFilter?: 'all' | 'running' | 'stopped'
}

export default function OcpVmsPanel({
  clusterId,
  listOnly = false,
  search = '',
  statusFilter = 'all',
}: Props) {
  const t = useT()
  const { user } = useAuth()
  const isAdmin = Boolean(user?.is_admin || user?.role === 'admin')
  const qc = useQueryClient()
  const [acting, setActing] = useState<string | null>(null)
  const [detailVm, setDetailVm] = useState<{ namespace: string; name: string } | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [page, setPage] = useState(1)

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['openshift-kubevirt-vms', clusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/kubevirt/vms`)
      if (!r.ok) return { vms: [] as VmRow[] }
      return r.json() as Promise<{ vms: VmRow[] }>
    },
    enabled: !!clusterId,
    refetchInterval: 30_000,
  })

  const vms = data?.vms || []

  const filtered = useMemo(() => {
    const ql = search.trim().toLowerCase()
    return vms.filter((v) => {
      const run = isRunning(v)
      if (statusFilter === 'running' && !run) return false
      if (statusFilter === 'stopped' && run) return false
      if (!ql) return true
      const blob = `${v.name} ${v.namespace} ${v.ip_address || ''} ${v.node || ''} ${v.node_name || ''} ${v.guest_os || ''}`.toLowerCase()
      return blob.includes(ql)
    })
  }, [vms, search, statusFilter])

  const sorted = useMemo(() => {
    const list = [...filtered]
    const dir = sortDir === 'asc' ? 1 : -1
    list.sort((a, b) => {
      const cpuA = a.cpu_count || a.cpu_cores || 0
      const cpuB = b.cpu_count || b.cpu_cores || 0
      const memA = a.memory_mb || (a.memory_gb || 0) * 1024
      const memB = b.memory_mb || (b.memory_gb || 0) * 1024
      const cpuPctA = cpuA && a.usage?.cpu_millicores ? a.usage.cpu_millicores / (cpuA * 1000) : -1
      const cpuPctB = cpuB && b.usage?.cpu_millicores ? b.usage.cpu_millicores / (cpuB * 1000) : -1
      const memPctA = memA && a.usage?.memory_mb ? a.usage.memory_mb / memA : -1
      const memPctB = memB && b.usage?.memory_mb ? b.usage.memory_mb / memB : -1
      switch (sortKey) {
        case 'namespace':
          return dir * (a.namespace || '').localeCompare(b.namespace || '', 'tr')
        case 'node':
          return dir * (a.node || a.node_name || '').localeCompare(b.node || b.node_name || '', 'tr')
        case 'ip': {
          const pa = ipSortKey(a.ip_address)
          const pb = ipSortKey(b.ip_address)
          for (let i = 0; i < 4; i++) {
            if ((pa[i] || 0) !== (pb[i] || 0)) return dir * ((pa[i] || 0) - (pb[i] || 0))
          }
          return 0
        }
        case 'cpu':
          return dir * (cpuA - cpuB)
        case 'memory':
          return dir * (memA - memB)
        case 'cpu_pct':
          return dir * (cpuPctA - cpuPctB)
        case 'mem_pct':
          return dir * (memPctA - memPctB)
        case 'status': {
          const ra = isRunning(a) ? 1 : 0
          const rb = isRunning(b) ? 1 : 0
          return dir * (ra - rb)
        }
        case 'name':
        default:
          return dir * (a.name || '').localeCompare(b.name || '', 'tr')
      }
    })
    return list
  }, [filtered, sortKey, sortDir])

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
  const pageSafe = Math.min(page, totalPages)
  const pageRows = useMemo(() => {
    const start = (pageSafe - 1) * PAGE_SIZE
    return sorted.slice(start, start + PAGE_SIZE)
  }, [sorted, pageSafe])

  React.useEffect(() => {
    setPage(1)
  }, [search, statusFilter, sortKey, sortDir, clusterId])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortKey(key)
      setSortDir(key === 'cpu_pct' || key === 'mem_pct' || key === 'cpu' || key === 'memory' ? 'desc' : 'asc')
    }
  }

  const SortTh = ({
    label, sk, className = '',
  }: { label: string; sk: SortKey; className?: string }) => (
    <th className={`text-left px-3 py-2 font-semibold ${className}`}>
      <button
        type="button"
        onClick={() => toggleSort(sk)}
        className="inline-flex items-center gap-1 hover:text-white transition-colors"
      >
        {label}
        {sortKey === sk ? (
          sortDir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
        ) : null}
      </button>
    </th>
  )

  const summary = useMemo(() => {
    const running = vms.filter(isRunning)
    const allocCpu = vms.reduce((s, v) => s + (v.cpu_count || v.cpu_cores || 0), 0)
    const allocMemGb = Math.round(
      (vms.reduce((s, v) => s + (v.memory_mb || (v.memory_gb || 0) * 1024), 0) / 1024) * 10,
    ) / 10
    const byNode: Record<string, number> = {}
    for (const v of running) {
      const n = v.node || v.node_name
      if (n) byNode[n] = (byNode[n] || 0) + 1
    }
    const topCpu = [...running]
      .filter((v) => v.usage?.cpu_millicores)
      .sort((a, b) => (b.usage?.cpu_millicores || 0) - (a.usage?.cpu_millicores || 0))
      .slice(0, 3)
    const topMem = [...running]
      .filter((v) => v.usage?.memory_mb)
      .sort((a, b) => (b.usage?.memory_mb || 0) - (a.usage?.memory_mb || 0))
      .slice(0, 3)
    return { running: running.length, allocCpu, allocMemGb, byNode, topCpu, topMem }
  }, [vms])

  const power = async (vm: VmRow, action: string) => {
    const key = `${vm.namespace}/${vm.name}`
    if (!window.confirm(t('ocp_power_confirm', { name: vm.name, action }))) return
    setActing(key)
    try {
      const r = await fetch(
        `${API_BASE_URL}/openshift/clusters/${clusterId}/kubevirt/vms/${encodeURIComponent(vm.namespace)}/${encodeURIComponent(vm.name)}/power`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }) },
      )
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        throw new Error(d.detail || `HTTP ${r.status}`)
      }
      setTimeout(() => qc.invalidateQueries({ queryKey: ['openshift-kubevirt-vms', clusterId] }), 2000)
    } catch (e) {
      alert(e instanceof Error ? e.message : t('ocp_action_fail'))
    } finally {
      setActing(null)
    }
  }

  return (
    <div className="space-y-4">
      {!listOnly && (
        <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
          <div className="flex items-center gap-2 mb-3">
            <MonitorPlay size={16} className="text-violet-400" />
            <h3 className="text-sm font-semibold text-slate-100">{t('ocp_virt_summary')}</h3>
            <button
              type="button"
              onClick={() => refetch()}
              className="ml-auto text-xs px-2 py-1 rounded-lg border border-white/[0.08] text-slate-400 hover:bg-white/[0.04] inline-flex items-center gap-1"
            >
              <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} /> {t('refresh_action')}
            </button>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
            <div className="rounded-lg border border-white/[0.06] bg-cyber-deep/40 px-3 py-2">
              <div className="text-slate-500">{t('ocp_total_vm')}</div>
              <div className="text-lg font-bold text-slate-100">{vms.length}</div>
              <div className="text-emerald-400 mt-0.5">{t('ocp_n_running', { n: summary.running })}</div>
              <div className="mt-2 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className="h-full bg-emerald-500"
                  style={{ width: `${vms.length ? (summary.running / vms.length) * 100 : 0}%` }}
                />
              </div>
            </div>
            <div className="rounded-lg border border-white/[0.06] bg-cyber-deep/40 px-3 py-2">
              <div className="text-slate-500">{t('ocp_alloc')}</div>
              <div className="text-slate-100 mt-1">{t('ocp_alloc_line', { cpu: summary.allocCpu, mem: summary.allocMemGb })}</div>
              <div className="text-slate-500 mt-2 text-[11px]">
                Node:{' '}
                {Object.entries(summary.byNode)
                  .map(([n, c]) => `${n.split('.')[0]}:${c}`)
                  .join(' · ') || '—'}
              </div>
            </div>
            <div className="rounded-lg border border-white/[0.06] bg-cyber-deep/40 px-3 py-2">
              <div className="text-slate-500 mb-1">{t('ocp_top_cpu')}</div>
              {summary.topCpu.length === 0 && <div className="text-slate-600">—</div>}
              {summary.topCpu.map((v) => {
                const cores = v.cpu_count || v.cpu_cores || 1
                const pct = ((v.usage?.cpu_millicores || 0) / (cores * 1000)) * 100
                return (
                  <div key={`${v.namespace}/${v.name}`} className="flex justify-between gap-2 text-[11px] py-0.5">
                    <span className="text-slate-300 truncate">{v.name}</span>
                    <span className="text-slate-500 tabular-nums">{pct.toFixed(1)}%</span>
                  </div>
                )
              })}
            </div>
            <div className="rounded-lg border border-white/[0.06] bg-cyber-deep/40 px-3 py-2">
              <div className="text-slate-500 mb-1">{t('ocp_top_mem')}</div>
              {summary.topMem.length === 0 && <div className="text-slate-600">—</div>}
              {summary.topMem.map((v) => {
                const total = v.memory_mb || (v.memory_gb || 0) * 1024 || 1
                const pct = ((v.usage?.memory_mb || 0) / total) * 100
                return (
                  <div key={`${v.namespace}/${v.name}`} className="py-0.5">
                    <div className="flex justify-between gap-2 text-[11px]">
                      <span className="text-slate-300 truncate">{v.name}</span>
                      <span className={`tabular-nums ${pct > 85 ? 'text-red-400' : 'text-slate-500'}`}>
                        {pct.toFixed(1)}%
                      </span>
                    </div>
                    <div className="h-1 rounded-full bg-slate-800 overflow-hidden mt-0.5">
                      <div
                        className={`h-full ${pct > 85 ? 'bg-red-500' : 'bg-blue-500'}`}
                        style={{ width: `${Math.min(100, pct)}%` }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4 space-y-2">
        <div className="flex items-center gap-2 mb-1">
          <MonitorPlay size={16} className="text-rose-400" />
          <h3 className="text-sm font-semibold text-slate-100">{t('ocp_vms_kubevirt')}</h3>
          <span className="text-xs text-slate-500">
            {filtered.length === vms.length ? vms.length : `${filtered.length}/${vms.length}`}
          </span>
          {listOnly && (
            <button
              type="button"
              onClick={() => refetch()}
              className="ml-auto text-xs px-2 py-1 rounded-lg border border-white/[0.08] text-slate-400 hover:bg-white/[0.04] inline-flex items-center gap-1"
            >
              <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} /> {t('refresh_action')}
            </button>
          )}
        </div>

        {filtered.length === 0 ? (
          <p className="text-sm text-slate-500 py-8 text-center">
            {isFetching ? t('loading') : vms.length === 0 ? t('ocp_no_kubevirt_vm') : t('ocp_vms_filter_empty')}
          </p>
        ) : (
          <>
            <div className="overflow-x-auto rounded-lg border border-white/[0.04]">
              <table className="w-full text-sm">
                <thead className="bg-white/[0.03] text-[10px] uppercase tracking-wider text-slate-500">
                  <tr>
                    <SortTh label={t('name')} sk="name" />
                    <SortTh label={t('ocp_col_project')} sk="namespace" />
                    <SortTh label={t('ocp_col_worker')} sk="node" className="hidden lg:table-cell" />
                    <SortTh label="IP" sk="ip" className="hidden md:table-cell" />
                    <SortTh label="CPU" sk="cpu" />
                    <SortTh label={t('memory')} sk="memory" />
                    <SortTh label="C %" sk="cpu_pct" className="hidden md:table-cell" />
                    <SortTh label="M %" sk="mem_pct" className="hidden md:table-cell" />
                    <SortTh label={t('col_status')} sk="status" />
                    <th className="text-right px-3 py-2" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {pageRows.map((vm) => {
                    const key = `${vm.namespace}/${vm.name}`
                    const running = isRunning(vm)
                    const cpu = vm.cpu_count || vm.cpu_cores || 0
                    const memMb = vm.memory_mb || Math.round((vm.memory_gb || 0) * 1024)
                    const memG = memMb ? Math.round((memMb / 1024) * 10) / 10 : null
                    const cpuPct =
                      running && vm.usage?.cpu_millicores && cpu
                        ? (vm.usage.cpu_millicores / (cpu * 1000)) * 100
                        : null
                    const memPct =
                      running && vm.usage?.memory_mb && memMb
                        ? (vm.usage.memory_mb / memMb) * 100
                        : null
                    const busy = acting === key
                    const osBlob = vm.guest_os || vm.os_type || ''

                    return (
                      <tr
                        key={key}
                        className="hover:bg-white/[0.03] cursor-pointer"
                        onClick={() => setDetailVm({ namespace: vm.namespace, name: vm.name })}
                      >
                        <td className="px-3 py-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <OsIcon os={osBlob || vm.name} size={22} className="flex-shrink-0" />
                            <div className="min-w-0">
                              <div className="text-slate-100 font-medium truncate">{vm.name}</div>
                              {osBlob ? (
                                <div className="text-[10px] text-slate-500 truncate">{osBlob}</div>
                              ) : null}
                            </div>
                          </div>
                        </td>
                        <td className="px-3 py-2 text-slate-400">{vm.namespace}</td>
                        <td className="px-3 py-2 text-slate-400 hidden lg:table-cell truncate max-w-[10rem]">
                          {(vm.node || vm.node_name || '—').split('.')[0]}
                        </td>
                        <td className="px-3 py-2 text-sky-500/90 font-mono text-xs hidden md:table-cell">
                          {vm.ip_address || '—'}
                        </td>
                        <td className="px-3 py-2 text-slate-300 tabular-nums">{cpu || '—'}</td>
                        <td className="px-3 py-2 text-slate-300 tabular-nums">{memG != null ? `${memG}G` : '—'}</td>
                        <td className="px-3 py-2 hidden md:table-cell">
                          <UsageBar label="C" pct={cpuPct} />
                        </td>
                        <td className="px-3 py-2 hidden md:table-cell">
                          <UsageBar label="M" pct={memPct} />
                        </td>
                        <td className="px-3 py-2">
                          <span
                            className={`text-[10px] px-2 py-0.5 rounded-full ${
                              running
                                ? 'bg-emerald-500/15 text-emerald-300'
                                : 'bg-slate-500/20 text-slate-400'
                            }`}
                          >
                            {running ? t('hv_running_now') : vm.printable_status || vm.phase || t('disabled')}
                          </span>
                        </td>
                        <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-end gap-0.5">
                            {busy ? (
                              <Loader2 size={14} className="animate-spin text-slate-500" />
                            ) : (
                              <>
                                {running && (
                                  <button
                                    type="button"
                                    title={t('ocp_console_novnc')}
                                    onClick={() => openVmConsole(clusterId, vm.namespace, vm.name)}
                                    className="p-1 rounded text-violet-400 hover:bg-violet-500/15"
                                  >
                                    <Monitor size={14} />
                                  </button>
                                )}
                                {isAdmin && (
                                  <>
                                    {!running && (
                                      <button
                                        type="button"
                                        title={t('start')}
                                        onClick={() => power(vm, 'start')}
                                        className="p-1 rounded text-emerald-400 hover:bg-emerald-500/15"
                                      >
                                        <Play size={14} />
                                      </button>
                                    )}
                                    {running && (
                                      <>
                                        <button
                                          type="button"
                                          title={t('restart')}
                                          onClick={() => power(vm, 'restart')}
                                          className="p-1 rounded text-sky-400 hover:bg-sky-500/15"
                                        >
                                          <RotateCcw size={14} />
                                        </button>
                                        <button
                                          type="button"
                                          title={t('stop')}
                                          onClick={() => power(vm, 'stop')}
                                          className="p-1 rounded text-red-400 hover:bg-red-500/15"
                                        >
                                          <Square size={14} />
                                        </button>
                                      </>
                                    )}
                                    <OcpVmAdminActions clusterId={clusterId} vm={vm} />
                                  </>
                                )}
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            {totalPages > 1 && (
              <div className="flex items-center justify-between text-xs text-slate-400 pt-1">
                <span>
                  {(pageSafe - 1) * PAGE_SIZE + 1}–{Math.min(pageSafe * PAGE_SIZE, sorted.length)} / {sorted.length}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    disabled={pageSafe <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    className="p-1 rounded border border-white/[0.08] disabled:opacity-30 hover:bg-white/[0.04]"
                  >
                    <ChevronLeft size={14} />
                  </button>
                  <span className="tabular-nums px-2">{pageSafe} / {totalPages}</span>
                  <button
                    type="button"
                    disabled={pageSafe >= totalPages}
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    className="p-1 rounded border border-white/[0.08] disabled:opacity-30 hover:bg-white/[0.04]"
                  >
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {detailVm && (
        <OcpVmDetailDrawer
          clusterId={clusterId}
          namespace={detailVm.namespace}
          name={detailVm.name}
          onClose={() => setDetailVm(null)}
        />
      )}
    </div>
  )
}
