import React, { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import { inventoryHeaders } from '../lib/inventoryApi'
import {
  Server, Cpu, MemoryStick, Power, PowerOff, Monitor, Search,
  Plus, Trash2, RefreshCw, ChevronDown, ChevronRight, LayoutDashboard,
  Database, Settings, X, Check, AlertTriangle, BarChart3, HardDrive,
  Network, Cloud, ExternalLink,
} from 'lucide-react'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis } from 'recharts'
import { isVmOnline, isPoweredOn as isPowerStateOn } from '../utils/powerState'
import { useT, useLocale } from '../i18n/LocaleProvider'

// DESIGN.md: "Mor (purple, violet) kullanılmaz — blue-600 tek aksan rengidir."
// `info` DESIGN.md'deki --info token'ıyla aynı (#38bdf8) — RAM/VM-sayısı gibi
// nötr metrikler için mavi ailesinden, accent'ten (blue) ayrışan ikinci ton.
const NEON = {
  green: '#22c55e', red: '#ef4444', orange: '#f97316',
  blue: '#3b82f6', cyan: '#06b6d4', info: '#38bdf8',
}

// ── Types ───────────────────────────────────────────────────────────────────
interface Hypervisor {
  id: number; name: string; type: string; hostname: string
  ip_address: string; port: number; username: string; connection_config: any
  status?: string
  sync_job?: SyncJob | null
}

interface SyncJob {
  status?: string
  phase?: string
  percent?: number
  message?: string
  vms_done?: number
  vms_total?: number
  error?: string
  synced_count?: number
  started_at?: string
  updated_at?: string
}

interface VM {
  id: number; name: string; hostname: string; ip_address: string
  status: string; os_type: string; cpu_cores: number; memory_gb: number
  hypervisor_id: number; hypervisor_vm_id: string; vm_power_state?: string
  ai_ready?: boolean
  disk_gb?: number
  platform?: string
}

interface VmDetailsPayload {
  server_id: number
  server_name?: string
  hypervisor_id?: number
  hypervisor_vm_id?: string
  vm_name?: string
  vm_guest_hostname?: string
  vm_guest_ip?: string
  vm_cpu_count?: number
  vm_memory_mb?: number
  vm_disk_gb?: number
  vm_power_state?: string
  vm_tools_status?: string
  vm_network_info?: { name?: string; mac?: string; ips?: { address: string; version?: string }[] }[]
  vm_cluster?: string
  vm_datastore?: string
  vm_hardware_version?: string
  vm_last_sync?: string | null
  can_snapshot?: boolean
}

interface VmLiveMetrics {
  server_id: number
  source?: string | null
  error?: string
  power_state?: string | null
  cpu_percent?: number | null
  mem_percent?: number | null
  disk_percent?: number | null
  mem_total_gb?: number | null
  mem_used_gb?: number | null
  disk_total_gb?: number | null
  disk_avail_gb?: number | null
  cpu_num?: number | null
  cpu_mhz?: number | null
  uptime_seconds?: number | null
  disk_read_iops?: number | null
  disk_write_iops?: number | null
  net_rx_kbps?: number | null
  net_tx_kbps?: number | null
}

interface EsxHost {
  host_name: string; host_ref?: string; cpu_usage_pct: number; mem_usage_pct: number
  cpu_total_mhz: number; cpu_usage_mhz: number; cpu_cores: number
  mem_total_mb: number; mem_used_mb: number; ds_total_gb: number; ds_used_gb: number
  ds_usage_pct: number; vms_running: number; vms_total: number
  connection_state?: string; power_state?: string; maintenance_mode?: boolean
  inventory?: { vendor?: string; model?: string; cpu_model?: string }
}

// ── Utilities ───────────────────────────────────────────────────────────────
const fmtMem = (mb: number) => mb >= 1024 ? `${(mb/1024).toFixed(0)} GB` : `${mb} MB`
const fmtDisk = (gb: number) => gb >= 1024 ? `${(gb/1024).toFixed(1)} TB` : `${gb.toFixed(0)} GB`

// ── Confirm Modal ───────────────────────────────────────────────────────────
const ConfirmModal = ({ message, onConfirm, onCancel }: {
  message: string; onConfirm: () => void; onCancel: () => void
}) => {
  const t = useT()
  return (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
    <div className="bg-cyber-card border border-slate-600 rounded-2xl shadow-2xl p-6 max-w-sm w-full mx-4">
      <div className="flex items-start gap-3 mb-5">
        <div className="w-9 h-9 rounded-full bg-yellow-500/15 border border-yellow-500/30 flex items-center justify-center flex-shrink-0">
          <AlertTriangle className="w-4 h-4 text-yellow-400" />
        </div>
        <div>
          <div className="text-sm font-semibold text-white mb-1">{t('confirm_title')}</div>
          <div className="text-sm text-slate-300 leading-relaxed">{message}</div>
        </div>
      </div>
      <div className="flex gap-3 justify-end">
        <button onClick={onCancel} className="px-4 py-2 rounded-lg text-sm text-slate-300 hover:text-white bg-white/[0.07] hover:bg-slate-600 border border-slate-600 transition-colors">{t('cancel')}</button>
        <button onClick={onConfirm} className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-red-600 hover:bg-red-500 border border-red-500/50 transition-colors">{t('confirm_ok')}</button>
      </div>
    </div>
  </div>
  )
}

// ── Stat Card ───────────────────────────────────────────────────────────────
const StatCard = ({ icon: Icon, label, value, sub, accent, trend }: {
  icon: any; label: string; value: string | number; sub?: string; accent: string; trend?: number
}) => (
  <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-4 hover:border-slate-600/50 transition-all group">
    <div className="flex items-start justify-between">
      <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: `${accent}20` }}>
        <Icon className="w-5 h-5" style={{ color: accent }} />
      </div>
      {trend !== undefined && (
        <span className={`text-xs px-2 py-0.5 rounded-full ${trend >= 0 ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
          {trend >= 0 ? '+' : ''}{trend}%
        </span>
      )}
    </div>
    <div className="mt-3">
      <div className="text-2xl font-bold text-white">{value}</div>
      <div className="text-xs text-slate-400 mt-0.5">{label}</div>
      {sub && <div className="text-[10px] text-slate-500">{sub}</div>}
    </div>
  </div>
)

// ── Resource Gauge ──────────────────────────────────────────────────────────
const ResourceGauge = ({ label, used, total, unit, accent }: {
  label: string; used: number; total: number; unit: string; accent: string
}) => {
  const t = useT()
  const pct = total > 0 ? Math.round((used / total) * 100) : 0
  const free = total - used
  const getColor = (p: number) => p >= 90 ? NEON.red : p >= 75 ? NEON.orange : accent

  return (
    <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-5">
      <div className="flex items-center justify-between mb-4">
        <span className="text-sm font-medium text-white">{label}</span>
        <span className="text-xs px-2 py-1 rounded-full" style={{ background: `${getColor(pct)}20`, color: getColor(pct) }}>
          {pct}%
        </span>
      </div>
      <div className="h-3 bg-slate-800 rounded-full overflow-hidden mb-3">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: `linear-gradient(90deg, ${accent}, ${getColor(pct)})`, boxShadow: `0 0 10px ${accent}60` }}
        />
      </div>
      <div className="flex justify-between text-xs">
        <span className="text-slate-400">{t('hv_used')}: <span className="text-white font-medium">{unit === 'GB' ? fmtDisk(used) : fmtMem(used)}</span></span>
        <span className="text-slate-400">{t('hv_free')}: <span className="text-green-400 font-medium">{unit === 'GB' ? fmtDisk(free) : fmtMem(free)}</span></span>
      </div>
    </div>
  )
}

// ── VM Status Pie ───────────────────────────────────────────────────────────
const VMStatusPie = ({ poweredOn, poweredOff }: { poweredOn: number; poweredOff: number }) => {
  const t = useT()
  const total = poweredOn + poweredOff
  if (total === 0) return null
  
  const data = [
    { name: t('hv_running'), value: poweredOn, color: NEON.green },
    { name: t('power_off'), value: poweredOff, color: '#475569' },
  ].filter(d => d.value > 0)

  return (
    <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-5">
      <h3 className="text-sm font-medium text-white mb-4">{t('hv_vm_status_dist')}</h3>
      <div className="flex items-center gap-6">
        <div className="relative">
          <ResponsiveContainer width={100} height={100}>
            <PieChart>
              <Pie data={data} cx="50%" cy="50%" innerRadius={30} outerRadius={45} paddingAngle={3} dataKey="value">
                {data.map((entry, i) => <Cell key={i} fill={entry.color} />)}
              </Pie>
              <Tooltip formatter={(v: number) => [`${v} VM`, '']} />
            </PieChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-lg font-bold text-white">{total}</span>
          </div>
        </div>
        <div className="flex-1 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Power className="w-4 h-4 text-green-400" />
              <span className="text-sm text-slate-300">{t('hv_running')}</span>
            </div>
            <span className="text-sm font-bold text-green-400">{poweredOn}</span>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <PowerOff className="w-4 h-4 text-slate-500" />
              <span className="text-sm text-slate-300">{t('power_off')}</span>
            </div>
            <span className="text-sm font-bold text-slate-400">{poweredOff}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Host Resource Bar Chart ─────────────────────────────────────────────────
const HostResourceChart = ({ hosts }: { hosts: EsxHost[] }) => {
  const t = useT()
  if (hosts.length === 0) return null

  const data = hosts.slice(0, 6).map(h => ({
    name: h.host_name.length > 12 ? h.host_name.slice(0, 12) + '...' : h.host_name,
    CPU: h.cpu_usage_pct || 0,
    Memory: h.mem_usage_pct || 0,
    Disk: h.ds_usage_pct || 0,
  }))

  return (
    <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-5">
      <h3 className="text-sm font-medium text-white mb-4">{t('hv_host_resource')}</h3>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} layout="vertical" margin={{ left: 0, right: 10 }}>
          <XAxis type="number" domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} width={80} axisLine={false} tickLine={false} />
          <Tooltip 
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
            formatter={(v: number) => [`${v}%`, '']}
          />
          <Bar dataKey="CPU" fill={NEON.cyan} radius={[0, 4, 4, 0]} barSize={8} />
          <Bar dataKey="Memory" fill={NEON.info} radius={[0, 4, 4, 0]} barSize={8} />
          <Bar dataKey="Disk" fill={NEON.orange} radius={[0, 4, 4, 0]} barSize={8} />
        </BarChart>
      </ResponsiveContainer>
      <div className="flex justify-center gap-4 mt-2">
        {[{ label: 'CPU', color: NEON.cyan }, { label: 'Memory', color: NEON.info }, { label: 'Disk', color: NEON.orange }].map(l => (
          <div key={l.label} className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full" style={{ background: l.color }} />
            <span className="text-xs text-slate-400">{l.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── VM Detail Drawer ────────────────────────────────────────────────────────
const VMDetailDrawer = ({
  vm,
  hypervisorName,
  onClose,
}: {
  vm: VM
  hypervisorName: string
  onClose: () => void
}) => {
  const t = useT()
  const { locale } = useLocale()
  const isOn = isVmOnline(vm.status, vm.vm_power_state)

  const { data: details, isLoading, isError, refetch, isFetching } = useQuery<VmDetailsPayload>({
    queryKey: ['hypervisor-vm-details', vm.id],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/snapshots/server/${vm.id}/vm-details`)
      if (!r.ok) throw new Error(t('hv_vm_detail_fail'))
      return r.json()
    },
    enabled: !!vm.id,
    staleTime: 30_000,
  })

  const {
    data: liveMetrics,
    isLoading: metricsLoading,
    isFetching: metricsFetching,
    isError: metricsError,
    refetch: refetchMetrics,
  } = useQuery<VmLiveMetrics>({
    queryKey: ['vm-live-metrics', vm.id],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/servers/${vm.id}/vm-live-metrics`)
      if (!r.ok) throw new Error(t('hv_metrics_err'))
      return r.json()
    },
    enabled: !!vm.id,
    staleTime: 20_000,
    refetchInterval: 60_000,
  })

  const [syncing, setSyncing] = useState(false)
  const syncVm = async () => {
    setSyncing(true)
    try {
      const r = await fetch(`${API_BASE_URL}/snapshots/server/${vm.id}/search-vm`, { method: 'POST' })
      if (!r.ok) {
        const err = await r.json().catch(() => ({}))
        throw new Error(err.detail || `HTTP ${r.status}`)
      }
      await Promise.all([refetch(), refetchMetrics()])
    } catch (e: any) {
      alert(e?.message || t('hv_refresh_fail'))
    } finally {
      setSyncing(false)
    }
  }

  const cpu = details?.vm_cpu_count ?? vm.cpu_cores
  const ramMb = details?.vm_memory_mb
  const ramGb = ramMb != null ? ramMb / 1024 : vm.memory_gb
  const diskGb = details?.vm_disk_gb ?? vm.disk_gb
  const power = details?.vm_power_state || vm.vm_power_state || vm.status
  const powerOn = isPowerStateOn(power) || isOn

  const pctColor = (v: number | null | undefined) =>
    v == null ? 'text-slate-500' : v > 85 ? 'text-red-400' : v > 60 ? 'text-amber-400' : 'text-emerald-400'
  const barColor = (v: number | null | undefined) =>
    v == null ? 'bg-slate-700' : v > 85 ? 'bg-red-500' : v > 60 ? 'bg-amber-500' : 'bg-emerald-500'
  const fmtKbps = (v: number | null | undefined) => {
    if (v == null) return '—'
    if (v >= 1024) return `${(v / 1024).toFixed(1)} MB/s`
    return `${v.toFixed(0)} KB/s`
  }

  const fields: { label: string; val?: string | number | null }[] = [
    { label: 'VM ID', val: details?.hypervisor_vm_id || vm.hypervisor_vm_id },
    { label: t('label_vm_name'), val: details?.vm_name || vm.name },
    { label: t('hv_guest_host'), val: details?.vm_guest_hostname || vm.hostname },
    { label: 'IP', val: details?.vm_guest_ip || vm.ip_address },
    { label: 'OS', val: vm.os_type },
    { label: t('hv_hypervisor'), val: hypervisorName },
    { label: 'Cluster', val: details?.vm_cluster },
    { label: t('hv_datastore'), val: details?.vm_datastore },
    { label: t('hw_version'), val: details?.vm_hardware_version },
    { label: t('hv_vmware_tools'), val: details?.vm_tools_status },
  ]

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/55 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md h-full bg-slate-900 border-l border-slate-700 shadow-2xl flex flex-col overflow-hidden">
        <div className="flex-none px-5 py-4 border-b border-slate-800 flex items-start justify-between gap-3">
          <div className="min-w-0 flex items-start gap-3">
            <div className={`w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0 ${powerOn ? 'bg-green-500/15' : 'bg-slate-700/60'}`}>
              <Monitor className={`w-5 h-5 ${powerOn ? 'text-green-400' : 'text-slate-400'}`} />
            </div>
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-white truncate">{vm.name}</h2>
              <p className="text-xs text-slate-500 truncate mt-0.5">{hypervisorName || 'Hypervisor'}</p>
              <span className={`inline-flex items-center gap-1 mt-2 px-2 py-0.5 rounded-full text-[10px] font-medium ${
                powerOn ? 'bg-green-500/15 text-green-400' : 'bg-slate-700/50 text-slate-400'
              }`}>
                {powerOn ? <Power className="w-3 h-3" /> : <PowerOff className="w-3 h-3" />}
                {powerOn ? t('hv_running_now') : t('power_off')}
              </span>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          <div className="grid grid-cols-3 gap-2">
            <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-3 text-center">
              <Cpu className="w-4 h-4 text-cyan-400 mx-auto mb-1" />
              <div className="text-lg font-bold text-white">{cpu ?? '—'}</div>
              <div className="text-[10px] text-slate-500">vCPU</div>
            </div>
            <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-3 text-center">
              <MemoryStick className="w-4 h-4 text-sky-400 mx-auto mb-1" />
              <div className="text-lg font-bold text-white">{ramGb != null ? Number(ramGb).toFixed(ramGb < 10 ? 1 : 0) : '—'}</div>
              <div className="text-[10px] text-slate-500">{t('hv_gb_memory')}</div>
            </div>
            <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-3 text-center">
              <HardDrive className="w-4 h-4 text-orange-400 mx-auto mb-1" />
              <div className="text-lg font-bold text-white">{diskGb ?? '—'}</div>
              <div className="text-[10px] text-slate-500">{t('hv_gb_disk')}</div>
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
                <BarChart3 className="w-3.5 h-3.5" /> {t('hv_live_metrics')}
              </h3>
              <button
                onClick={() => refetchMetrics()}
                disabled={metricsLoading || metricsFetching}
                className="text-[11px] px-2 py-1 rounded-lg border border-slate-700 text-slate-400 hover:text-white hover:border-slate-500 disabled:opacity-50 flex items-center gap-1"
              >
                <RefreshCw className={`w-3 h-3 ${metricsFetching ? 'animate-spin' : ''}`} />
                {t('refresh_action')}
              </button>
            </div>
            {metricsLoading ? (
              <div className="flex items-center justify-center py-6">
                <RefreshCw className="w-5 h-5 text-slate-500 animate-spin" />
              </div>
            ) : metricsError || !liveMetrics?.source ? (
              <p className="text-xs text-amber-400/90 bg-amber-500/5 border border-amber-500/20 rounded-lg px-3 py-2">
                {liveMetrics?.error || t('hv_metrics_fail')}
              </p>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-[10px]">
                  <span className="px-2 py-0.5 rounded-full bg-blue-500/15 text-blue-300 border border-blue-500/25">vCenter</span>
                  {liveMetrics.uptime_seconds != null && (
                    <span className="text-slate-500">
                      {t('hv_uptime', { d: Math.floor(liveMetrics.uptime_seconds / 86400), h: Math.floor((liveMetrics.uptime_seconds % 86400) / 3600) })}
                    </span>
                  )}
                </div>
                {[
                  {
                    label: 'CPU',
                    value: liveMetrics.cpu_percent,
                    hint: liveMetrics.cpu_mhz != null ? `${liveMetrics.cpu_mhz} MHz` : (liveMetrics.cpu_num != null ? `${liveMetrics.cpu_num} vCPU` : undefined),
                  },
                  {
                    label: 'Memory',
                    value: liveMetrics.mem_percent,
                    hint: liveMetrics.mem_used_gb != null && liveMetrics.mem_total_gb != null
                      ? `${liveMetrics.mem_used_gb}/${liveMetrics.mem_total_gb} GB`
                      : undefined,
                  },
                  {
                    label: 'Disk',
                    value: liveMetrics.disk_percent,
                    hint: liveMetrics.disk_avail_gb != null && liveMetrics.disk_total_gb != null
                      ? t('hv_disk_free', { avail: liveMetrics.disk_avail_gb, total: liveMetrics.disk_total_gb })
                      : t('hv_guest_tools'),
                  },
                ].map(m => (
                  <div key={m.label}>
                    <div className="flex items-center justify-between text-xs mb-1">
                      <span className="text-slate-400">{m.label}{m.hint ? ` · ${m.hint}` : ''}</span>
                      <span className={`font-semibold tabular-nums ${pctColor(m.value)}`}>
                        {m.value != null ? `${m.value.toFixed(1)}%` : '—'}
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${barColor(m.value)}`}
                        style={{ width: `${Math.min(100, Math.max(0, m.value ?? 0))}%` }}
                      />
                    </div>
                  </div>
                ))}
                <div className="grid grid-cols-2 gap-2 pt-1">
                  <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 px-3 py-2">
                    <div className="text-[10px] text-slate-500 mb-0.5">{t('hv_disk_iops')}</div>
                    <div className="text-sm text-slate-200 tabular-nums">
                      R {liveMetrics.disk_read_iops != null ? liveMetrics.disk_read_iops.toFixed(0) : '—'}
                      <span className="text-slate-600"> / </span>
                      W {liveMetrics.disk_write_iops != null ? liveMetrics.disk_write_iops.toFixed(0) : '—'}
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 px-3 py-2">
                    <div className="text-[10px] text-slate-500 mb-0.5 flex items-center gap-1">
                      <Network className="w-3 h-3" /> {t('hv_network')}
                    </div>
                    <div className="text-sm text-slate-200 tabular-nums">
                      ↓ {fmtKbps(liveMetrics.net_rx_kbps)}
                      <span className="text-slate-600"> · </span>
                      ↑ {fmtKbps(liveMetrics.net_tx_kbps)}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
                <Cloud className="w-3.5 h-3.5" /> {t('hv_vm_info')}
              </h3>
              <button
                onClick={syncVm}
                disabled={syncing || isFetching}
                className="text-[11px] px-2 py-1 rounded-lg border border-slate-700 text-slate-400 hover:text-white hover:border-slate-500 disabled:opacity-50 flex items-center gap-1"
              >
                <RefreshCw className={`w-3 h-3 ${syncing || isFetching ? 'animate-spin' : ''}`} />
                {t('refresh_action')}
              </button>
            </div>
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <RefreshCw className="w-5 h-5 text-slate-500 animate-spin" />
              </div>
            ) : isError ? (
              <p className="text-xs text-amber-400 mb-2">{t('hv_details_fail')}</p>
            ) : null}
            <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 divide-y divide-slate-800/80">
              {fields.filter(f => f.val != null && f.val !== '').map(f => (
                <div key={f.label} className="flex items-start justify-between gap-3 px-3 py-2.5 text-sm">
                  <span className="text-slate-500 flex-shrink-0">{f.label}</span>
                  <span className="text-slate-200 text-right break-all font-mono text-xs">{String(f.val)}</span>
                </div>
              ))}
            </div>
            {details?.vm_last_sync && (
              <p className="text-[10px] text-slate-600 mt-2">
                {t('hv_last_sync', { time: new Date(details.vm_last_sync).toLocaleString(locale === 'en' ? 'en-US' : 'tr-TR') })}
              </p>
            )}
          </div>

          {(details?.vm_network_info?.length ?? 0) > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <Network className="w-3.5 h-3.5" /> {t('hv_nics')}
              </h3>
              <div className="space-y-2">
                {details!.vm_network_info!.map((nic, i) => (
                  <div key={i} className="rounded-lg border border-slate-700/50 bg-slate-800/30 px-3 py-2.5">
                    <div className="text-sm text-slate-200">{nic.name || `NIC ${i + 1}`}</div>
                    {nic.mac && <div className="text-[11px] text-slate-500 font-mono mt-0.5">{nic.mac}</div>}
                    {nic.ips?.map(ip => (
                      <div key={ip.address} className="text-[11px] text-cyan-400 font-mono mt-0.5">
                        {ip.address}{ip.version ? ` (${ip.version})` : ''}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )}

          {!details?.hypervisor_vm_id && !vm.hypervisor_vm_id && !isLoading && (
            <p className="text-xs text-slate-500 bg-slate-800/40 border border-slate-700/50 rounded-lg px-3 py-2">
              {t('hv_vm_id_hint')}
            </p>
          )}
        </div>

        <div className="flex-none px-5 py-3 border-t border-slate-800 flex gap-2">
          <Link
            to={`/servers?highlight=${vm.id}`}
            className="flex-1 text-center text-xs px-3 py-2.5 rounded-xl border border-slate-700 text-slate-300 hover:text-white hover:border-slate-500 flex items-center justify-center gap-1.5"
          >
            <ExternalLink className="w-3.5 h-3.5" /> {t('hv_server_record')}
          </Link>
          <button
            onClick={onClose}
            className="px-4 py-2.5 rounded-xl bg-slate-800 text-slate-300 text-xs hover:text-white border border-slate-700"
          >
            {t('close')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── VM Table ────────────────────────────────────────────────────────────────
const VMTable = ({ vms, hypervisors }: { vms: VM[]; hypervisors: Hypervisor[] }) => {
  const t = useT()
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'online' | 'offline'>('all')
  const [sortBy, setSortBy] = useState<'name' | 'cpu' | 'ram'>('name')
  const [selectedVm, setSelectedVm] = useState<VM | null>(null)

  const hvMap = useMemo(() => {
    const m: Record<number, string> = {}
    hypervisors.forEach(h => { m[h.id] = h.name })
    return m
  }, [hypervisors])

  const filtered = useMemo(() => {
    let list = [...vms]
    
    if (search) {
      const q = search.toLowerCase()
      list = list.filter(v => v.name.toLowerCase().includes(q) || v.ip_address?.includes(q) || v.os_type?.toLowerCase().includes(q))
    }
    
    if (filter === 'online') {
      list = list.filter(v => isVmOnline(v.status, v.vm_power_state))
    } else if (filter === 'offline') {
      list = list.filter(v => !isVmOnline(v.status, v.vm_power_state))
    }
    
    if (sortBy === 'cpu') list.sort((a, b) => (b.cpu_cores || 0) - (a.cpu_cores || 0))
    else if (sortBy === 'ram') list.sort((a, b) => (b.memory_gb || 0) - (a.memory_gb || 0))
    else list.sort((a, b) => a.name.localeCompare(b.name))
    
    return list
  }, [vms, search, filter, sortBy])

  const isPoweredOn = (vm: VM) => isVmOnline(vm.status, vm.vm_power_state)

  return (
    <div className="bg-cyber-card rounded-xl border border-white/[0.06] overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 border-b border-white/[0.06] flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Monitor className="w-5 h-5 text-blue-400" />
          <span className="text-sm font-medium text-white">{t('hv_virtual_machines')}</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-400">{vms.length}</span>
        </div>
        <div className="flex items-center gap-2">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              placeholder={t('hv_vm_search')}
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="bg-cyber-deep border border-white/[0.06] rounded-lg pl-9 pr-3 py-1.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50 w-48"
            />
          </div>
          {/* Filter */}
          <select
            value={filter}
            onChange={e => setFilter(e.target.value as any)}
            className="bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500/50"
          >
            <option value="all">{t('filter_all')}</option>
            <option value="online">{t('hv_running')}</option>
            <option value="offline">{t('power_off')}</option>
          </select>
          {/* Sort */}
          <select
            value={sortBy}
            onChange={e => setSortBy(e.target.value as any)}
            className="bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500/50"
          >
            <option value="name">{t('hv_sort_name')}</option>
            <option value="cpu">{t('hv_sort_cpu')}</option>
            <option value="ram">{t('memory')}</option>
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
        <table className="w-full">
          <thead className="bg-slate-800/50 sticky top-0">
            <tr className="text-xs text-slate-400 uppercase">
              <th className="text-left px-5 py-3 font-medium">VM</th>
              <th className="text-left px-5 py-3 font-medium">Hypervisor</th>
              <th className="text-left px-5 py-3 font-medium">IP</th>
              <th className="text-left px-5 py-3 font-medium">OS</th>
              <th className="text-center px-5 py-3 font-medium">CPU</th>
              <th className="text-center px-5 py-3 font-medium">Memory</th>
              <th className="text-center px-5 py-3 font-medium">{t('col_status')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.04]">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-5 py-12 text-center text-slate-500">
                  {search || filter !== 'all' ? t('hv_no_vm_filter') : t('hv_no_vm')}
                </td>
              </tr>
            ) : (
              filtered.slice(0, 100).map(vm => (
                <tr
                  key={vm.id}
                  onClick={() => setSelectedVm(vm)}
                  className={`hover:bg-blue-500/5 transition-colors cursor-pointer ${
                    selectedVm?.id === vm.id ? 'bg-blue-500/10' : ''
                  }`}
                >
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${isPoweredOn(vm) ? 'bg-green-500/15' : 'bg-slate-700/50'}`}>
                        <Server className={`w-4 h-4 ${isPoweredOn(vm) ? 'text-green-400' : 'text-slate-500'}`} />
                      </div>
                      <div>
                        <div className="text-sm font-medium text-blue-300">{vm.name}</div>
                        {vm.ai_ready && <span className="text-[10px] text-cyan-400">{t('ai_ready')}</span>}
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-3 text-sm text-slate-400">{hvMap[vm.hypervisor_id] || '-'}</td>
                  <td className="px-5 py-3 text-sm text-slate-300 font-mono">{vm.ip_address || '-'}</td>
                  <td className="px-5 py-3 text-sm text-slate-400">{vm.os_type || '-'}</td>
                  <td className="px-5 py-3 text-center">
                    <span className="text-sm text-white font-medium">{vm.cpu_cores || '-'}</span>
                    {vm.cpu_cores > 0 && <span className="text-xs text-slate-500 ml-1">vCPU</span>}
                  </td>
                  <td className="px-5 py-3 text-center">
                    <span className="text-sm text-white font-medium">{vm.memory_gb || '-'}</span>
                    {vm.memory_gb > 0 && <span className="text-xs text-slate-500 ml-1">GB</span>}
                  </td>
                  <td className="px-5 py-3 text-center">
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                      isPoweredOn(vm) ? 'bg-green-500/15 text-green-400' : 'bg-slate-700/50 text-slate-400'
                    }`}>
                      {isPoweredOn(vm) ? <Power className="w-3 h-3" /> : <PowerOff className="w-3 h-3" />}
                      {isPoweredOn(vm) ? t('hv_running_now') : t('power_off')}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {filtered.length > 100 && (
          <div className="px-5 py-3 text-center text-xs text-slate-500 border-t border-white/[0.04]">
            {t('hv_showing_first', { n: filtered.length })}
          </div>
        )}
      </div>

      {selectedVm && (
        <VMDetailDrawer
          vm={selectedVm}
          hypervisorName={hvMap[selectedVm.hypervisor_id] || '-'}
          onClose={() => setSelectedVm(null)}
        />
      )}
    </div>
  )
}

// ── Host Cards ──────────────────────────────────────────────────────────────
const HostCard = ({ host, hvName }: { host: EsxHost; hvName: string }) => {
  const t = useT()
  const [expanded, setExpanded] = useState(false)
  const getStatusColor = (pct: number) => pct >= 90 ? NEON.red : pct >= 75 ? NEON.orange : NEON.green

  return (
    <div className="bg-cyber-card rounded-xl border border-white/[0.06] overflow-hidden hover:border-slate-600/50 transition-all">
      <div 
        className="px-5 py-4 flex items-center justify-between cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-cyan-500/20 to-blue-500/20 flex items-center justify-center">
            <Database className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <div className="text-sm font-medium text-white">{host.host_name}</div>
            <div className="text-xs text-slate-500">{t('hv_host_vms', { hv: hvName, running: host.vms_running, total: host.vms_total })}</div>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {/* Quick Stats */}
          <div className="flex gap-3">
            <div className="text-center">
              <div className="text-xs font-bold" style={{ color: getStatusColor(host.cpu_usage_pct) }}>{host.cpu_usage_pct?.toFixed(0) || 0}%</div>
              <div className="text-[10px] text-slate-500">CPU</div>
            </div>
            <div className="text-center">
              <div className="text-xs font-bold" style={{ color: getStatusColor(host.mem_usage_pct) }}>{host.mem_usage_pct?.toFixed(0) || 0}%</div>
              <div className="text-[10px] text-slate-500">Memory</div>
            </div>
            <div className="text-center">
              <div className="text-xs font-bold" style={{ color: getStatusColor(host.ds_usage_pct) }}>{host.ds_usage_pct?.toFixed(0) || 0}%</div>
              <div className="text-[10px] text-slate-500">Disk</div>
            </div>
          </div>
          {expanded ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
        </div>
      </div>

      {expanded && (
        <div className="px-5 py-4 border-t border-white/[0.06] bg-slate-900/30 space-y-4">
          {/* Resource Bars */}
          {[
            { label: 'CPU', used: host.cpu_usage_mhz, total: host.cpu_total_mhz, unit: 'MHz', pct: host.cpu_usage_pct, color: NEON.cyan },
            { label: 'Memory', used: host.mem_used_mb, total: host.mem_total_mb, unit: 'MB', pct: host.mem_usage_pct, color: NEON.info },
            { label: 'Disk', used: host.ds_used_gb, total: host.ds_total_gb, unit: 'GB', pct: host.ds_usage_pct, color: NEON.orange },
          ].map(r => (
            <div key={r.label}>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-400">{r.label}</span>
                <span className="text-slate-300">
                  {r.unit === 'GB' ? fmtDisk(r.used) : fmtMem(r.used)} / {r.unit === 'GB' ? fmtDisk(r.total) : fmtMem(r.total)}
                  <span className="ml-2" style={{ color: getStatusColor(r.pct) }}>({r.pct?.toFixed(0)}%)</span>
                </span>
              </div>
              <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                <div className="h-full rounded-full transition-all" style={{ width: `${r.pct}%`, background: r.color }} />
              </div>
            </div>
          ))}

          {/* Hardware Info */}
          {host.inventory && (
            <div className="pt-2 border-t border-white/[0.04] grid grid-cols-2 gap-2 text-xs">
              {host.inventory.vendor && <div><span className="text-slate-500">{t('hv_brand')}:</span> <span className="text-slate-300">{host.inventory.vendor}</span></div>}
              {host.inventory.model && <div><span className="text-slate-500">{t('hv_model')}:</span> <span className="text-slate-300">{host.inventory.model}</span></div>}
              {host.inventory.cpu_model && <div className="col-span-2"><span className="text-slate-500">CPU:</span> <span className="text-slate-300">{host.inventory.cpu_model}</span></div>}
              <div><span className="text-slate-500">{t('hv_core')}:</span> <span className="text-slate-300">{host.cpu_cores}</span></div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Hypervisor Management Section ───────────────────────────────────────────
const HypervisorManagement = ({ 
  hypervisors, 
  onAdd, 
  onDelete, 
  onSync,
  onSyncAll,
  onShowProgress,
  syncingAll = false,
  readOnly = false,
}: { 
  hypervisors: Hypervisor[]
  onAdd: () => void
  onDelete: (id: number) => void
  onSync: (id: number) => void
  onSyncAll?: () => void
  onShowProgress?: (id: number) => void
  syncingAll?: boolean
  readOnly?: boolean
}) => {
  const t = useT()
  const getTypeColor = (type: string) => {
    const colors: Record<string, string> = {
      vmware: 'from-green-500 to-green-600',
      hyperv: 'from-blue-500 to-blue-600',
      kvm: 'from-orange-500 to-orange-600',
      xen: 'from-blue-600 to-blue-700',
      proxmox: 'from-red-500 to-red-600',
      openshift_virt: 'from-rose-600 to-red-700',
    }
    return colors[type.toLowerCase()] || 'from-slate-500 to-slate-600'
  }

  const getTypeLabel = (type: string) => {
    const labels: Record<string, string> = { vmware: 'VMware', hyperv: 'Hyper-V', kvm: 'oVirt/KVM', xen: 'XEN', proxmox: 'Proxmox', openshift_virt: t('hv_type_ocp_virt') }
    return labels[type.toLowerCase()] || type.toUpperCase()
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-white">{t('hv_connections')}</h3>
          {!readOnly && (
            <p className="text-xs text-slate-500 mt-0.5">{t('hv_auto_sync')}</p>
          )}
        </div>
        {!readOnly && (
          <div className="flex items-center gap-2">
            {hypervisors.length > 0 && (
              <button
                onClick={onSyncAll}
                disabled={syncingAll}
                className="flex items-center gap-2 px-3 py-1.5 bg-blue-500/10 text-blue-400 text-sm rounded-lg hover:bg-blue-500/20 transition-all disabled:opacity-50"
              >
                <RefreshCw className={`w-4 h-4 ${syncingAll ? 'animate-spin' : ''}`} /> {t('hv_sync_all')}
              </button>
            )}
            <button
              onClick={onAdd}
              className="flex items-center gap-2 px-3 py-1.5 bg-gradient-to-r from-blue-600 to-blue-700 text-white text-sm rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all"
            >
              <Plus className="w-4 h-4" /> {t('add')}
            </button>
          </div>
        )}
      </div>

      {hypervisors.length === 0 ? (
        <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-12 text-center">
          <Database className="w-12 h-12 text-slate-600 mx-auto mb-3" />
          <p className="text-slate-400 mb-4">{t('hv_no_connection')}</p>
          {readOnly ? (
            <Link to="/integrations/hypervisors" className="text-blue-400 hover:text-blue-300 text-sm">
              {t('hv_integrations_link')}
            </Link>
          ) : (
            <button onClick={onAdd} className="text-blue-400 hover:text-blue-300 text-sm">{t('hv_add_hypervisor')}</button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {hypervisors.map(hv => (
            <div key={hv.id} className="bg-cyber-card rounded-xl border border-white/[0.06] p-5 hover:border-slate-600/50 transition-all">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-lg bg-gradient-to-br ${getTypeColor(hv.type)} flex items-center justify-center`}>
                    <span className="text-xs font-bold text-white">{hv.type?.slice(0, 2).toUpperCase()}</span>
                  </div>
                  <div>
                    <div className="text-sm font-medium text-white flex items-center gap-2">
                      {hv.name}
                      {(hv.sync_job?.status === 'running' || hv.status === 'SYNCING') && (
                        <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/30">
                          <RefreshCw className="w-2.5 h-2.5 animate-spin" /> {t('hv_scanning')}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-500">{getTypeLabel(hv.type)}</div>
                  </div>
                </div>
              </div>
              <div className="space-y-1.5 text-xs mb-4">
                <div className="flex"><span className="w-12 text-slate-500">IP:</span><span className="text-slate-300 font-mono">{hv.ip_address}:{hv.port}</span></div>
                <div className="flex"><span className="w-12 text-slate-500">{t('hv_user')}:</span><span className="text-slate-300">{hv.username}</span></div>
              </div>
              {(hv.sync_job?.status === 'running' || hv.status === 'SYNCING') && (
                <div className="mb-3">
                  <div className="flex justify-between text-[10px] text-slate-400 mb-1">
                    <span className="truncate pr-2">{hv.sync_job?.message || t('hv_scan_progress')}</span>
                    <span>{Math.round(Number(hv.sync_job?.percent) || 0)}%</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                    <div className="h-full bg-blue-500 transition-all" style={{ width: `${Math.max(3, Number(hv.sync_job?.percent) || 3)}%` }} />
                  </div>
                </div>
              )}
              {!readOnly && (
                <div className="flex gap-2">
                  <button
                    onClick={() => onSync(hv.id)}
                    disabled={hv.sync_job?.status === 'running' || hv.status === 'SYNCING'}
                    className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-blue-500/10 text-blue-400 rounded-lg hover:bg-blue-500/20 text-xs transition-colors disabled:opacity-50"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${(hv.sync_job?.status === 'running' || hv.status === 'SYNCING') ? 'animate-spin' : ''}`} />
                    {(hv.sync_job?.status === 'running' || hv.status === 'SYNCING') ? t('hv_scanning_dots') : t('hv_sync_vms')}
                  </button>
                  <button
                    onClick={() => onDelete(hv.id)}
                    className="px-3 py-2 bg-red-500/10 text-red-400 rounded-lg hover:bg-red-500/20 text-xs transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
              {(hv.sync_job?.status === 'running' || hv.status === 'SYNCING') && onShowProgress && (
                <button
                  type="button"
                  onClick={() => onShowProgress(hv.id)}
                  className="mt-2 w-full text-[11px] text-blue-400 hover:text-blue-300 py-1"
                >
                  {t('hv_open_progress')}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Sync Scanning Overlay ───────────────────────────────────────────────────
const SyncScanningOverlay = ({
  hypervisorId,
  hypervisorName,
  queueLabel,
  onDone,
  onDismiss,
}: {
  hypervisorId: number
  hypervisorName: string
  queueLabel?: string
  onDone: (job: SyncJob) => void
  onDismiss: () => void
}) => {
  const tr = useT()
  const [job, setJob] = useState<SyncJob>({ status: 'running', percent: 1, message: tr('hv_scan_starting') })
  const [vmCount, setVmCount] = useState(0)
  const [elapsedSec, setElapsedSec] = useState(0)
  const startedAtRef = React.useRef(Date.now())
  const serverStartedAtRef = React.useRef<number | null>(null)

  const onDoneRef = React.useRef(onDone)
  onDoneRef.current = onDone

  useEffect(() => {
    startedAtRef.current = Date.now()
    serverStartedAtRef.current = null
    setElapsedSec(0)
    const tick = setInterval(() => {
      const origin = serverStartedAtRef.current ?? startedAtRef.current
      setElapsedSec(Math.max(0, Math.floor((Date.now() - origin) / 1000)))
    }, 1000)
    return () => clearInterval(tick)
  }, [hypervisorId])

  useEffect(() => {
    let cancelled = false
    let finished = false
    setJob({ status: 'running', percent: 1, message: tr('hv_scan_starting') })
    const tick = async () => {
      if (finished || cancelled) return
      try {
        const r = await fetch(`${API_BASE_URL}/hypervisors/${hypervisorId}/sync-status`, {
          headers: inventoryHeaders(),
        })
        if (!r.ok || cancelled) return
        const data = await r.json()
        const j: SyncJob = data.sync_job || {}
        if (j.started_at) {
          const ts = Date.parse(j.started_at)
          if (!Number.isNaN(ts)) serverStartedAtRef.current = ts
        }
        setJob(j.status ? j : { status: 'running', percent: 3, message: tr('hv_connecting') })
        setVmCount(data.vm_count_in_db || 0)
        if (j.status === 'done' || j.status === 'error') {
          finished = true
          onDoneRef.current(j)
        }
      } catch {
        /* poll again */
      }
    }
    tick()
    const id = setInterval(tick, 2000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [hypervisorId])

  const pct = Math.max(0, Math.min(100, Number(job.percent) || 0))
  const done = job.status === 'done' || job.status === 'error'
  const fmtDur = (sec: number) => {
    if (sec < 60) return tr('dur_sec', { n: sec })
    const m = Math.floor(sec / 60)
    const s = sec % 60
    if (m < 60) return tr('dur_min_sec', { m, s })
    return tr('dur_hr_min', { h: Math.floor(m / 60), m: m % 60 })
  }
  const etaSec =
    !done && pct >= 8 && elapsedSec >= 15
      ? Math.max(0, Math.round((elapsedSec / pct) * (100 - pct)))
      : null

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-[60] p-4">
      <div className="bg-cyber-card rounded-2xl border border-white/[0.08] w-full max-w-lg shadow-2xl p-6">
        <div className="flex items-start gap-4 mb-5">
          <div className={`w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0 ${
            job.status === 'error' ? 'bg-red-500/15' : job.status === 'done' ? 'bg-green-500/15' : 'bg-blue-500/15'
          }`}>
            {job.status === 'error' ? (
              <AlertTriangle className="w-6 h-6 text-red-400" />
            ) : job.status === 'done' ? (
              <Check className="w-6 h-6 text-green-400" />
            ) : (
              <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold text-white">
              {job.status === 'done' ? tr('hv_scan_done') : job.status === 'error' ? tr('hv_scan_error') : tr('hv_scanning_title')}
            </h2>
            <p className="text-sm text-slate-400 mt-0.5 truncate">{hypervisorName}</p>
            {queueLabel && <p className="text-xs text-blue-400/80 mt-1">{queueLabel}</p>}
          </div>
        </div>

        <div className="mb-4">
          <div className="flex justify-between text-xs text-slate-400 mb-1.5">
            <span className="truncate pr-2">{job.message || tr('job_processing')}</span>
            <span className="font-mono text-slate-300 flex-shrink-0">{pct}%</span>
          </div>
          <div className="h-2.5 rounded-full bg-slate-800 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                job.status === 'error' ? 'bg-red-500' : job.status === 'done' ? 'bg-green-500' : 'bg-blue-500'
              }`}
              style={{ width: `${pct || 3}%` }}
            />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3 mb-5">
          <div className="bg-slate-800/60 rounded-lg px-3 py-2.5 border border-white/[0.04]">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">{tr('hv_vm_progress')}</div>
            <div className="text-sm text-white font-medium mt-0.5">
              {job.vms_done != null && job.vms_total != null
                ? `${job.vms_done} / ${job.vms_total}`
                : '—'}
            </div>
          </div>
          <div className="bg-slate-800/60 rounded-lg px-3 py-2.5 border border-white/[0.04]">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">{tr('job_elapsed')}</div>
            <div className="text-sm text-white font-medium mt-0.5">{fmtDur(elapsedSec)}</div>
          </div>
          <div className="bg-slate-800/60 rounded-lg px-3 py-2.5 border border-white/[0.04]">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">{tr('job_eta')}</div>
            <div className="text-sm text-white font-medium mt-0.5">
              {done ? '—' : etaSec != null ? `~${fmtDur(etaSec)}` : tr('job_eta_calc')}
            </div>
          </div>
        </div>
        {vmCount > 0 && (
          <p className="text-[11px] text-slate-500 mb-3">{tr('hv_db_vms', { n: vmCount })}</p>
        )}

        {!done && (
          <p className="text-xs text-slate-500 mb-4 leading-relaxed">
            {tr('hv_scan_hint')}
          </p>
        )}
        {job.status === 'error' && job.error && (
          <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 mb-4">
            {job.error}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onDismiss}
            className="px-4 py-2 rounded-lg text-sm text-slate-300 bg-white/[0.07] hover:bg-slate-600 border border-slate-600"
          >
            {done ? tr('close') : tr('job_continue_bg')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Add Hypervisor Modal ────────────────────────────────────────────────────
const AddHypervisorModal = ({ onClose, onCreate }: { onClose: () => void; onCreate: (data: any) => void }) => {
  const t = useT()
  const [formData, setFormData] = useState({
    name: '', type: 'vmware', hostname: '', ip_address: '', port: 443, username: '', password: '', token: ''
  })
  const [ocpAuthMethod, setOcpAuthMethod] = useState<'token' | 'credentials'>('token')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const isTokenAuth = formData.type === 'openshift_virt'

  const buildOpenShiftPayload = () => ({
    name: formData.name,
    type: formData.type,
    api_url: formData.ip_address,
    ...(ocpAuthMethod === 'token'
      ? { token: formData.token }
      : { username: formData.username, password: formData.password }),
  })

  const testConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const r = await fetch(`${API_BASE_URL}/hypervisors/test-connection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          isTokenAuth
            ? buildOpenShiftPayload()
            : { type: formData.type, hostname: formData.hostname || formData.ip_address, ip_address: formData.ip_address, port: formData.port, username: formData.username, password: formData.password }
        )
      })
      const data = await r.json()
      setTestResult({ success: data.success, message: data.message })
    } catch {
      setTestResult({ success: false, message: t('conn_error') })
    } finally {
      setTesting(false)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!testResult?.success) return
    onCreate(isTokenAuth ? buildOpenShiftPayload() : formData)
    onClose()
  }

  const canTest = isTokenAuth
    ? Boolean(formData.ip_address) && (ocpAuthMethod === 'token' ? Boolean(formData.token) : Boolean(formData.username) && Boolean(formData.password))
    : Boolean(formData.username) && Boolean(formData.password)

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-cyber-card rounded-2xl border border-white/[0.06] w-full max-w-md shadow-2xl">
        <div className="px-6 py-4 border-b border-white/[0.06] flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">{t('hv_add_title')}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">{t('hv_name_req')}</label>
            <input type="text" required value={formData.name} onChange={e => { setFormData({...formData, name: e.target.value}); setTestResult(null) }}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50" placeholder="vCenter Production" />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">{t('hv_type_req')}</label>
            <select value={formData.type} onChange={e => { setFormData({...formData, type: e.target.value}); setTestResult(null) }}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50">
              <option value="vmware">VMware vCenter / ESXi</option>
              <option value="hyperv">Microsoft Hyper-V</option>
              <option value="kvm">KVM / oVirt</option>
              <option value="proxmox">Proxmox VE</option>
              <option value="openshift_virt">{t('hv_type_ocp_virt')}</option>
            </select>
          </div>
          {isTokenAuth ? (
            <>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">{t('hv_auth_method')}</label>
                <div className="grid grid-cols-2 gap-2 p-1 bg-cyber-deep border border-white/[0.06] rounded-lg">
                  <button type="button" onClick={() => { setOcpAuthMethod('token'); setTestResult(null) }}
                    className={`py-1.5 rounded-md text-sm font-medium transition-colors ${ocpAuthMethod === 'token' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'}`}>
                    {t('hv_bearer')}
                  </button>
                  <button type="button" onClick={() => { setOcpAuthMethod('credentials'); setTestResult(null) }}
                    className={`py-1.5 rounded-md text-sm font-medium transition-colors ${ocpAuthMethod === 'credentials' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'}`}>
                    {t('hv_user_pass')}
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">{t('hv_api_url')}</label>
                <input type="text" required value={formData.ip_address} onChange={e => { setFormData({...formData, ip_address: e.target.value}); setTestResult(null) }}
                  className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50" placeholder="https://api.cluster.example.com:6443" />
              </div>
              {ocpAuthMethod === 'token' ? (
                <div>
                  <label className="block text-xs text-slate-400 mb-1.5">{t('hv_token_req')}</label>
                  <textarea required value={formData.token} onChange={e => { setFormData({...formData, token: e.target.value}); setTestResult(null) }}
                    rows={3}
                    className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50 font-mono" placeholder="Service Account token (oc whoami -t / sa/token secret)" />
                </div>
              ) : (
                <>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1.5">{t('hv_username_req')}</label>
                    <input type="text" required value={formData.username} onChange={e => { setFormData({...formData, username: e.target.value}); setTestResult(null) }}
                      className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50" placeholder="kubeadmin" />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1.5">{t('hv_password')}</label>
                    <input type="password" required value={formData.password} onChange={e => { setFormData({...formData, password: e.target.value}); setTestResult(null) }}
                      className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50" />
                  </div>
                  <p className="text-[11px] text-slate-500 leading-relaxed">
                    {t('hv_oauth_hint')}
                  </p>
                </>
              )}
            </>
          ) : (
            <>
              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2">
                  <label className="block text-xs text-slate-400 mb-1.5">{t('hv_ip_req')}</label>
                  <input type="text" required value={formData.ip_address} onChange={e => { setFormData({...formData, ip_address: e.target.value}); setTestResult(null) }}
                    className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50" placeholder="192.168.1.100" />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1.5">{t('hv_port')}</label>
                  <input type="number" value={formData.port} onChange={e => { setFormData({...formData, port: parseInt(e.target.value) || 443}); setTestResult(null) }}
                    className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50" />
                </div>
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">{t('hv_username_req')}</label>
                <input type="text" required value={formData.username} onChange={e => { setFormData({...formData, username: e.target.value}); setTestResult(null) }}
                  className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50" placeholder="administrator@vsphere.local" />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">{t('hv_password')}</label>
                <input type="password" required value={formData.password} onChange={e => { setFormData({...formData, password: e.target.value}); setTestResult(null) }}
                  className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50" />
              </div>
            </>
          )}

          <button type="button" onClick={testConnection} disabled={testing || !canTest}
            className="w-full py-2.5 bg-blue-600/20 text-blue-400 border border-blue-500/30 rounded-lg hover:bg-blue-600/30 disabled:opacity-50 text-sm font-medium flex items-center justify-center gap-2">
            {testing ? <><RefreshCw className="w-4 h-4 animate-spin" /> {t('hv_testing')}</> : t('hv_test_conn')}
          </button>

          {testResult && (
            <div className={`p-3 rounded-lg border ${testResult.success ? 'bg-green-500/10 border-green-500/30' : 'bg-red-500/10 border-red-500/30'}`}>
              <div className="flex items-center gap-2">
                {testResult.success ? <Check className="w-4 h-4 text-green-400" /> : <X className="w-4 h-4 text-red-400" />}
                <span className={`text-sm ${testResult.success ? 'text-green-400' : 'text-red-400'}`}>{testResult.message}</span>
              </div>
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 px-4 py-2.5 bg-white/[0.07] text-white rounded-lg hover:bg-slate-600 text-sm">{t('cancel')}</button>
            <button type="submit" disabled={!testResult?.success}
              className="flex-1 px-4 py-2.5 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 disabled:opacity-50 text-sm font-medium">
              {t('add')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// ── Main Component ────────────────────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════════════════════
const Hypervisors: React.FC<{ allowInventoryEdit?: boolean }> = ({ allowInventoryEdit = false }) => {
  const t = useT()
  const [activeTab, setActiveTab] = useState<'dashboard' | 'vms' | 'hosts' | 'hypervisors'>(allowInventoryEdit ? 'hypervisors' : 'dashboard')
  const [showAddModal, setShowAddModal] = useState(false)
  const [scanTarget, setScanTarget] = useState<{ id: number; name: string } | null>(null)
  const [scanQueue, setScanQueue] = useState<{ id: number; name: string }[]>([])
  const [confirmState, setConfirmState] = useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const [selectedVm, setSelectedVm] = useState<VM | null>(null)
  const showConfirm = (msg: string): Promise<boolean> => new Promise(resolve => setConfirmState({ msg, resolve }))
  const queryClient = useQueryClient()

  // Hypervisors — tarama sırasında sık yenile (kart progress bar)
  const { data: hypervisors = [], isLoading: hvLoading } = useQuery<Hypervisor[]>({
    queryKey: ['hypervisors'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/`)
      if (!r.ok) throw new Error(t('hv_list_fail'))
      return r.json()
    },
    refetchInterval: (q) => {
      const list = (q.state.data as Hypervisor[] | undefined) || []
      const syncing = list.some(h => h.sync_job?.status === 'running' || h.status === 'SYNCING')
      return syncing || scanTarget ? 4000 : 60_000
    },
  })

  const [vmPage, setVmPage] = useState(1)
  const vmPageSize = 50

  // VMs — backend ile aynı tanım: hypervisor_id dolu OLUŞTU ya da server_type=VIRTUAL
  const { data: vmsPage } = useQuery({
    queryKey: ['servers', 'platform=virt', vmPage, vmPageSize],
    queryFn: async () => {
      const { fetchServersPage } = await import('../api/servers')
      return fetchServersPage<VM>({ platform: 'virt', page: vmPage, page_size: vmPageSize })
    },
    refetchInterval: 60_000,
  })
  const vms = vmsPage?.items ?? []
  const vmsTotal = vmsPage?.total ?? 0

  const { data: virtSummary } = useQuery({
    queryKey: ['servers-summary', 'virt'],
    queryFn: async () => {
      const { fetchServersSummary } = await import('../api/servers')
      return fetchServersSummary('virt')
    },
    refetchInterval: 60_000,
  })

  // ESX Host Metrics
  const [allHosts, setAllHosts] = useState<{ hvName: string; host: EsxHost }[]>([])
  const [hostsLoading, setHostsLoading] = useState(true)

  useEffect(() => {
    const vmwareHvs = hypervisors.filter(h => h.type?.toLowerCase() === 'vmware')
    if (vmwareHvs.length === 0) { setHostsLoading(false); return }

    fetch(`${API_BASE_URL}/hypervisors/host-metrics`)
      .then(r => r.ok ? r.json() : null)
      .then((data: { hosts?: { hvName: string; host: EsxHost }[] } | null) => {
        setAllHosts((data?.hosts || []).map(row => ({ hvName: row.hvName, host: row.host })))
        setHostsLoading(false)
      })
      .catch(() => { setAllHosts([]); setHostsLoading(false) })
  }, [hypervisors])

  const dismissedProgressRef = React.useRef<Set<number>>(new Set())

  // Mutations
  const startScan = async (id: number, name: string, queue?: { id: number; name: string }[]) => {
    const r = await fetch(`${API_BASE_URL}/hypervisors/${id}/sync-vms?background=true`, {
      method: 'POST',
      headers: inventoryHeaders(),
    })
    if (!r.ok) throw new Error((await r.json()).detail || t('hv_sync_fail'))
    if (queue && queue.length > 0) setScanQueue(queue)
    else setScanQueue([])
    dismissedProgressRef.current.delete(id)
    setScanTarget({ id, name })
    queryClient.invalidateQueries({ queryKey: ['hypervisors'] })
    return r.json()
  }

  const createMutation = useMutation({
    mutationFn: async (data: any) => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/`, {
        method: 'POST',
        headers: inventoryHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(data),
      })
      if (!r.ok) throw new Error((await r.json()).detail || t('hv_add_fail'))
      return r.json()
    },
    onSuccess: async (created) => {
      queryClient.invalidateQueries({ queryKey: ['hypervisors'] })
      try {
        await startScan(created.id, created.name)
      } catch (e) {
        alert(e instanceof Error ? e.message : t('hv_scan_fail'))
      }
    },
    onError: (e) => alert(e instanceof Error ? e.message : t('hv_add_fail')),
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/${id}`, { method: 'DELETE', headers: inventoryHeaders() })
      if (!r.ok) throw new Error(t('hv_delete_fail'))
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hypervisors'] })
      queryClient.invalidateQueries({ queryKey: ['servers'] })
    }
  })

  const syncMutation = useMutation({
    mutationFn: async (id: number) => {
      const hv = hypervisors.find(h => h.id === id)
      return startScan(id, hv?.name || `Hypervisor #${id}`)
    },
    onError: (e) => alert(e instanceof Error ? e.message : t('hv_sync_error')),
  })

  const [syncingAll, setSyncingAll] = useState(false)

  const syncAllMutation = useMutation({
    mutationFn: async () => {
      const list = hypervisors.map(h => ({ id: h.id, name: h.name }))
      if (list.length === 0) throw new Error(t('hv_no_hv'))
      setSyncingAll(true)
      // Sırayla: ilkini başlat, kalanı kuyruğa al — overlay bitince sonraki başlar
      const [first, ...rest] = list
      await startScan(first.id, first.name, list)
      return { queued: list.length, rest }
    },
    onError: (e) => {
      setSyncingAll(false)
      alert(e instanceof Error ? e.message : t('hv_sync_all_fail'))
    },
  })

  const advanceScanQueue = async (finishedId: number) => {
    queryClient.invalidateQueries({ queryKey: ['servers'] })
    queryClient.invalidateQueries({ queryKey: ['hypervisors'] })
    const idx = scanQueue.findIndex(h => h.id === finishedId)
    const after = idx >= 0 ? scanQueue.slice(idx + 1) : []
    if (after.length > 0) {
      const n = after[0]
      try {
        await startScan(n.id, n.name, scanQueue)
      } catch (e) {
        setSyncingAll(false)
        setScanQueue([])
        alert(e instanceof Error ? e.message : t('hv_next_scan_fail'))
      }
    } else {
      // Overlay "tamamlandı" durumunda kalsın; kullanıcı Kapat ile kapatır
      setScanQueue([])
      setSyncingAll(false)
    }
  }

  const openProgress = (id: number) => {
    const hv = hypervisors.find(h => h.id === id)
    if (!hv) return
    dismissedProgressRef.current.delete(id)
    setScanTarget({ id: hv.id, name: hv.name })
  }

  // Sayfa açılınca veya tarama devam ederken progress overlay'i göster
  useEffect(() => {
    if (scanTarget || hvLoading) return
    const running = hypervisors.find(
      h =>
        (h.sync_job?.status === 'running' || h.status === 'SYNCING') &&
        !dismissedProgressRef.current.has(h.id)
    )
    if (running) {
      setScanTarget({ id: running.id, name: running.name })
    }
  }, [hypervisors, scanTarget, hvLoading])

  const queueLabel = (() => {
    if (!scanTarget || scanQueue.length <= 1) return undefined
    const idx = scanQueue.findIndex(h => h.id === scanTarget.id)
    if (idx < 0) return t('hv_queue_n', { n: scanQueue.length })
    return t('hv_queue_pos', { i: idx + 1, n: scanQueue.length })
  })()

  // Stats (toplamlar summary'den; sayfa içeriği vms)
  const poweredOn = virtSummary?.online ?? vms.filter(v => isVmOnline(v.status, v.vm_power_state)).length
  const poweredOff = Math.max(0, (virtSummary?.total ?? vmsTotal) - poweredOn)
  const totalVmCpu = virtSummary?.cpu_cores ?? vms.reduce((acc, v) => acc + (v.cpu_cores || 0), 0)
  const totalVmRam = virtSummary?.memory_gb ?? vms.reduce((acc, v) => acc + (v.memory_gb || 0), 0)

  // Host totals
  const totalHostCpu = allHosts.reduce((acc, h) => acc + (h.host.cpu_total_mhz || 0), 0)
  const usedHostCpu = allHosts.reduce((acc, h) => acc + (h.host.cpu_usage_mhz || 0), 0)
  const totalHostMem = allHosts.reduce((acc, h) => acc + (h.host.mem_total_mb || 0), 0)
  const usedHostMem = allHosts.reduce((acc, h) => acc + (h.host.mem_used_mb || 0), 0)
  const totalHostDisk = allHosts.reduce((acc, h) => acc + (h.host.ds_total_gb || 0), 0)
  const usedHostDisk = allHosts.reduce((acc, h) => acc + (h.host.ds_used_gb || 0), 0)

  if (hvLoading) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center">
        <div className="w-12 h-12 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <>
      {confirmState && <ConfirmModal message={confirmState.msg} onConfirm={() => { confirmState.resolve(true); setConfirmState(null) }} onCancel={() => { confirmState.resolve(false); setConfirmState(null) }} />}
      {allowInventoryEdit && showAddModal && <AddHypervisorModal onClose={() => setShowAddModal(false)} onCreate={data => createMutation.mutate(data)} />}
      {scanTarget && (
        <SyncScanningOverlay
          hypervisorId={scanTarget.id}
          hypervisorName={scanTarget.name}
          queueLabel={queueLabel}
          onDone={() => {
            advanceScanQueue(scanTarget.id)
          }}
          onDismiss={() => {
            if (scanTarget) dismissedProgressRef.current.add(scanTarget.id)
            setScanTarget(null)
            setScanQueue([])
            setSyncingAll(false)
            queryClient.invalidateQueries({ queryKey: ['servers'] })
            queryClient.invalidateQueries({ queryKey: ['hypervisors'] })
          }}
        />
      )}

      <div className="space-y-6">
        <div>
          {allowInventoryEdit ? (
            <>
              <Link to="/integrations" className="text-xs text-slate-500 hover:text-white">← {t('nav_inventory_hub')}</Link>
              <h1 className="text-xl font-bold text-white mt-1">{t('hv_title_mgmt')}</h1>
              <p className="text-sm text-slate-500">{t('hv_subtitle_mgmt')}</p>
            </>
          ) : (
            <>
              <h1 className="text-xl font-bold text-white">{t('hv_title_dash')}</h1>
              <p className="text-sm text-slate-500">{t('hv_subtitle_dash')}</p>
              <Link to="/integrations/hypervisors" className="inline-block mt-2 text-xs text-blue-400 hover:text-blue-300">
                {t('hv_inventory_mgmt')}
              </Link>
            </>
          )}
        </div>
        {!allowInventoryEdit && (
          <>
            {/* Quick Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
              <StatCard icon={Database} label={t('hv_hypervisor')} value={hypervisors.length} sub={t('hv_n_vmware', { n: hypervisors.filter(h => h.type === 'vmware').length })} accent={NEON.blue} />
              <StatCard icon={Server} label="Host" value={allHosts.length} sub="ESX/KVM" accent={NEON.cyan} />
              <StatCard icon={Monitor} label={t('hv_stat_total_vm')} value={virtSummary?.total ?? vmsTotal} sub={t('hv_sub_running', { n: poweredOn })} accent={NEON.info} />
              <StatCard icon={Power} label={t('hv_stat_active_vm')} value={poweredOn} sub={t('hv_sub_off', { n: poweredOff })} accent={NEON.green} />
              <StatCard icon={Cpu} label={t('hv_stat_vcpu')} value={totalVmCpu} sub={t('hv_sub_cores')} accent={NEON.orange} />
              <StatCard icon={MemoryStick} label={t('hv_stat_mem')} value={`${totalVmRam} GB`} sub={t('hv_sub_mem')} accent={NEON.red} />
            </div>

            <div className="flex justify-end">
              <Link
                to="/infra-reports"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm border border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 transition-colors"
              >
                <BarChart3 className="w-4 h-4" />
                {t('nav_infra_reports')}
              </Link>
            </div>
          </>
        )}

        {/* Tabs */}
        <div className="flex gap-1 p-1 bg-cyber-card rounded-xl border border-white/[0.06] w-fit">
          {(allowInventoryEdit
            ? [{ id: 'hypervisors', icon: Settings, label: t('hv_tab_hvs') }]
            : [
                { id: 'dashboard', icon: LayoutDashboard, label: t('nav_dashboard') },
                { id: 'vms', icon: Monitor, label: t('hv_tab_vms') },
                { id: 'hosts', icon: Database, label: t('hv_tab_hosts') },
                { id: 'hypervisors', icon: Settings, label: t('hv_tab_hvs') },
              ]
          ).map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-all ${
                activeTab === tab.id 
                  ? 'bg-blue-600 text-white' 
                  : 'text-slate-400 hover:text-white hover:bg-white/[0.05]'
              }`}
            >
              <tab.icon className="w-4 h-4" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        {!allowInventoryEdit && activeTab === 'dashboard' && (
          <div className="space-y-6">
            {/* Resource Gauges */}
            {allHosts.length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <ResourceGauge label={t('hv_cpu_usage')} used={usedHostCpu} total={totalHostCpu} unit="MHz" accent={NEON.cyan} />
                <ResourceGauge label={t('hv_mem_usage')} used={usedHostMem} total={totalHostMem} unit="MB" accent={NEON.info} />
                <ResourceGauge label={t('hv_disk_usage')} used={usedHostDisk} total={totalHostDisk} unit="GB" accent={NEON.orange} />
              </div>
            )}

            {/* Charts Row */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <VMStatusPie poweredOn={poweredOn} poweredOff={poweredOff} />
              <HostResourceChart hosts={allHosts.map(h => h.host)} />
            </div>

            {/* Recent VMs */}
            {vms.length > 0 && (
              <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-medium text-white">{t('hv_recent_vms')}</h3>
                  <button onClick={() => setActiveTab('vms')} className="text-xs text-blue-400 hover:text-blue-300">{t('hv_see_all')}</button>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                  {vms.slice(0, 8).map(vm => {
                    const isOn = isVmOnline(vm.status, vm.vm_power_state)
                    return (
                      <button
                        key={vm.id}
                        type="button"
                        onClick={() => setSelectedVm(vm)}
                        className="flex items-center gap-3 p-3 bg-slate-800/50 rounded-lg text-left hover:bg-blue-500/10 hover:ring-1 hover:ring-blue-500/30 transition-colors"
                      >
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${isOn ? 'bg-green-500/15' : 'bg-slate-700'}`}>
                          <Server className={`w-4 h-4 ${isOn ? 'text-green-400' : 'text-slate-500'}`} />
                        </div>
                        <div className="min-w-0">
                          <div className="text-sm text-blue-300 truncate">{vm.name}</div>
                          <div className="text-xs text-slate-500">{vm.cpu_cores} vCPU • {vm.memory_gb} GB</div>
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {!allowInventoryEdit && activeTab === 'vms' && (
          <div className="space-y-3">
            <VMTable vms={vms} hypervisors={hypervisors} />
            {vmsTotal > 0 && (
              <div className="flex items-center justify-between text-sm text-slate-400 px-1">
                <span>{(vmPage - 1) * vmPageSize + 1}–{Math.min(vmPage * vmPageSize, vmsTotal)} / {vmsTotal}</span>
                <div className="flex items-center gap-2">
                  <button type="button" disabled={vmPage <= 1} onClick={() => setVmPage(p => Math.max(1, p - 1))}
                    className="px-3 py-1 rounded-lg bg-cyber-card border border-white/[0.08] disabled:opacity-40">{t('page_prev')}</button>
                  <span>{vmPage} / {Math.max(1, Math.ceil(vmsTotal / vmPageSize))}</span>
                  <button type="button" disabled={vmPage * vmPageSize >= vmsTotal} onClick={() => setVmPage(p => p + 1)}
                    className="px-3 py-1 rounded-lg bg-cyber-card border border-white/[0.08] disabled:opacity-40">{t('page_next')}</button>
                </div>
              </div>
            )}
          </div>
        )}

        {!allowInventoryEdit && activeTab === 'hosts' && (
          <div className="space-y-4">
            {hostsLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="w-8 h-8 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
              </div>
            ) : allHosts.length === 0 ? (
              <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-12 text-center">
                <Database className="w-12 h-12 text-slate-600 mx-auto mb-3" />
                <p className="text-slate-400">{t('hv_no_host')}</p>
                <p className="text-xs text-slate-500 mt-1">
                  {allowInventoryEdit ? t('hv_no_host_edit') : t('hv_no_host_view')}
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {allHosts.map(({ hvName, host }) => (
                  <HostCard key={`${hvName}-${host.host_name}`} host={host} hvName={hvName} />
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'hypervisors' && (
          <HypervisorManagement
            hypervisors={hypervisors}
            readOnly={!allowInventoryEdit}
            onAdd={() => setShowAddModal(true)}
            onDelete={async (id) => {
              if (await showConfirm(t('hv_delete_confirm'))) {
                deleteMutation.mutate(id)
              }
            }}
            onSync={(id) => syncMutation.mutate(id)}
            onSyncAll={() => syncAllMutation.mutate()}
            onShowProgress={openProgress}
            syncingAll={syncingAll || syncAllMutation.isPending}
          />
        )}
      </div>

      {selectedVm && (
        <VMDetailDrawer
          vm={selectedVm}
          hypervisorName={hypervisors.find(h => h.id === selectedVm.hypervisor_id)?.name || '-'}
          onClose={() => setSelectedVm(null)}
        />
      )}
    </>
  )
}

export default Hypervisors
