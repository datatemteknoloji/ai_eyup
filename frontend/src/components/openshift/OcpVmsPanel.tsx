/**
 * KubeVirt VM listesi — Atlas KubeVirtSection'a yakın: özet + satır içi C/M + VNC konsol.
 */
import React, { useMemo, useState } from 'react'
import {
  ChevronDown, ChevronRight, Cpu, Globe, Loader2, MemoryStick,
  Monitor, MonitorPlay, Play, RefreshCw, RotateCcw, Square,
} from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../../config/api'
import { useAuth } from '../../auth/AuthContext'
import OcpVmAdminActions from './OcpVmAdminActions'

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
  usage?: { cpu_millicores?: number; memory_mb?: number } | null
}

function openVmConsole(clusterId: number, namespace: string, name: string) {
  const title = encodeURIComponent(`${namespace}/${name}`)
  const url =
    `/openshift/vms/${clusterId}/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/console?title=${title}`
  window.open(url, `ocp-console-${namespace}-${name}`, 'width=1280,height=800')
}

function UsageBar({ label, pct }: { label: string; pct: number | null }) {
  const p = pct == null ? null : Math.max(0, Math.min(100, pct))
  const color =
    p == null ? 'bg-slate-600' : p > 85 ? 'bg-red-500' : p > 70 ? 'bg-amber-500' : 'bg-blue-500'
  return (
    <span className="flex items-center gap-1" title={`${label} kullanımı`}>
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

export default function OcpVmsPanel({ clusterId }: { clusterId: number }) {
  const { user } = useAuth()
  const isAdmin = Boolean(user?.is_admin || user?.role === 'admin')
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState<string | null>(null)
  const [acting, setActing] = useState<string | null>(null)

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

  const summary = useMemo(() => {
    const running = vms.filter(
      (v) =>
        (v.power_state || '').toLowerCase() === 'poweredon' ||
        (v.phase || v.printable_status || '').toLowerCase() === 'running',
    )
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
    if (!window.confirm(`${vm.name}: ${action}?`)) return
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
      alert(e instanceof Error ? e.message : 'İşlem başarısız')
    } finally {
      setActing(null)
    }
  }

  return (
    <div className="space-y-4">
      {/* Sanallaştırma özeti — Atlas Virtualization Overview benzeri */}
      <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <MonitorPlay size={16} className="text-violet-400" />
          <h3 className="text-sm font-semibold text-slate-100">Sanallaştırma özeti</h3>
          <button
            type="button"
            onClick={() => refetch()}
            className="ml-auto text-xs px-2 py-1 rounded-lg border border-white/[0.08] text-slate-400 hover:bg-white/[0.04] inline-flex items-center gap-1"
          >
            <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} /> Yenile
          </button>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
          <div className="rounded-lg border border-white/[0.06] bg-cyber-deep/40 px-3 py-2">
            <div className="text-slate-500">Toplam VM</div>
            <div className="text-lg font-bold text-slate-100">{vms.length}</div>
            <div className="text-emerald-400 mt-0.5">{summary.running} çalışan</div>
            <div className="mt-2 h-1.5 rounded-full bg-slate-800 overflow-hidden">
              <div
                className="h-full bg-emerald-500"
                style={{ width: `${vms.length ? (summary.running / vms.length) * 100 : 0}%` }}
              />
            </div>
          </div>
          <div className="rounded-lg border border-white/[0.06] bg-cyber-deep/40 px-3 py-2">
            <div className="text-slate-500">Ayrılan kaynak</div>
            <div className="text-slate-100 mt-1">{summary.allocCpu} vCPU · {summary.allocMemGb} GB RAM</div>
            <div className="text-slate-500 mt-2 text-[11px]">
              Node:{' '}
              {Object.entries(summary.byNode)
                .map(([n, c]) => `${n.split('.')[0]}:${c}`)
                .join(' · ') || '—'}
            </div>
          </div>
          <div className="rounded-lg border border-white/[0.06] bg-cyber-deep/40 px-3 py-2">
            <div className="text-slate-500 mb-1">En çok CPU</div>
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
            <div className="text-slate-500 mb-1">En çok bellek</div>
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

      {/* VM listesi */}
      <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4 space-y-2">
        <div className="flex items-center gap-2 mb-1">
          <MonitorPlay size={16} className="text-rose-400" />
          <h3 className="text-sm font-semibold text-slate-100">Sanal Makineler (KubeVirt)</h3>
          <span className="text-xs text-slate-500">{vms.length}</span>
        </div>

        {vms.length === 0 ? (
          <p className="text-sm text-slate-500 py-8 text-center">
            {isFetching ? 'Yükleniyor…' : 'Bu kümede KubeVirt VM yok.'}
          </p>
        ) : (
          <div className="space-y-1.5">
            {vms.map((vm) => {
              const key = `${vm.namespace}/${vm.name}`
              const running =
                (vm.power_state || '').toLowerCase() === 'poweredon' ||
                (vm.phase || vm.printable_status || '').toLowerCase() === 'running'
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
              const open = expanded === key
              const busy = acting === key

              return (
                <div key={key} className="rounded-lg border border-white/[0.05] bg-cyber-deep/30">
                  <div className="flex items-center gap-2 px-3 py-2 text-xs flex-wrap">
                    <button
                      type="button"
                      onClick={() => setExpanded(open ? null : key)}
                      className="text-slate-500 hover:text-slate-300"
                    >
                      {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </button>
                    <span
                      className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                        running ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'
                      }`}
                    />
                    <span className="text-slate-100 font-medium">{vm.name}</span>
                    <span className="text-slate-500">{vm.namespace}</span>
                    <span className="flex items-center gap-2 text-slate-500">
                      <span className="inline-flex items-center gap-0.5">
                        <Cpu size={11} />
                        {cpu || '—'}
                      </span>
                      <span className="inline-flex items-center gap-0.5">
                        <MemoryStick size={11} />
                        {memG != null ? `${memG}G` : '—'}
                      </span>
                      {vm.ip_address && (
                        <span className="inline-flex items-center gap-0.5 text-sky-600">
                          <Globe size={11} />
                          {vm.ip_address}
                        </span>
                      )}
                    </span>
                    {running && (
                      <span className="hidden md:flex items-center gap-3 ml-1">
                        <UsageBar label="C" pct={cpuPct} />
                        <UsageBar label="M" pct={memPct} />
                      </span>
                    )}
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded-full ml-auto flex-shrink-0 ${
                        running
                          ? 'bg-emerald-500/15 text-emerald-300'
                          : 'bg-slate-500/20 text-slate-400'
                      }`}
                    >
                      {running ? 'Çalışıyor' : vm.printable_status || vm.phase || 'Kapalı'}
                    </span>

                    <div className="flex items-center gap-0.5 flex-shrink-0">
                      {busy ? (
                        <Loader2 size={14} className="animate-spin text-slate-500" />
                      ) : (
                        <>
                          {running && (
                            <button
                              type="button"
                              title="Konsol (noVNC)"
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
                                  title="Başlat"
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
                                    title="Yeniden başlat"
                                    onClick={() => power(vm, 'restart')}
                                    className="p-1 rounded text-sky-400 hover:bg-sky-500/15"
                                  >
                                    <RotateCcw size={14} />
                                  </button>
                                  <button
                                    type="button"
                                    title="Durdur"
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
                  </div>
                  {open && (
                    <div className="border-t border-white/[0.06] px-4 py-3 text-[11px] text-slate-400 grid sm:grid-cols-3 gap-2">
                      <div>
                        Node: <span className="text-slate-200 font-mono">{vm.node || vm.node_name || '—'}</span>
                      </div>
                      <div>
                        CPU kullanım:{' '}
                        <span className="text-slate-200">
                          {vm.usage?.cpu_millicores != null ? `${vm.usage.cpu_millicores}m` : '—'}
                        </span>
                      </div>
                      <div>
                        Bellek kullanım:{' '}
                        <span className="text-slate-200">
                          {vm.usage?.memory_mb != null
                            ? `${(vm.usage.memory_mb / 1024).toFixed(1)} GiB`
                            : '—'}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
