import React, { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import { inventoryHeaders } from '../lib/inventoryApi'
import {
  Server, Cpu, MemoryStick, Power, PowerOff, Monitor, Search,
  Plus, Trash2, RefreshCw, ChevronDown, ChevronRight, LayoutDashboard,
  Database, Settings, X, Check, AlertTriangle, BarChart3,
} from 'lucide-react'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis } from 'recharts'

const NEON = {
  green: '#22c55e', red: '#ef4444', orange: '#f97316',
  blue: '#3b82f6', cyan: '#06b6d4', purple: '#a855f7',
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
}

interface VM {
  id: number; name: string; hostname: string; ip_address: string
  status: string; os_type: string; cpu_cores: number; memory_gb: number
  hypervisor_id: number; hypervisor_vm_id: string; vm_power_state?: string
  ai_ready?: boolean
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
}) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
    <div className="bg-cyber-card border border-slate-600 rounded-2xl shadow-2xl p-6 max-w-sm w-full mx-4">
      <div className="flex items-start gap-3 mb-5">
        <div className="w-9 h-9 rounded-full bg-yellow-500/15 border border-yellow-500/30 flex items-center justify-center flex-shrink-0">
          <AlertTriangle className="w-4 h-4 text-yellow-400" />
        </div>
        <div>
          <div className="text-sm font-semibold text-white mb-1">Onay Gerekiyor</div>
          <div className="text-sm text-slate-300 leading-relaxed">{message}</div>
        </div>
      </div>
      <div className="flex gap-3 justify-end">
        <button onClick={onCancel} className="px-4 py-2 rounded-lg text-sm text-slate-300 hover:text-white bg-white/[0.07] hover:bg-slate-600 border border-slate-600 transition-colors">İptal</button>
        <button onClick={onConfirm} className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-red-600 hover:bg-red-500 border border-red-500/50 transition-colors">Onayla</button>
      </div>
    </div>
  </div>
)

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
        <span className="text-slate-400">Kullanılan: <span className="text-white font-medium">{unit === 'GB' ? fmtDisk(used) : fmtMem(used)}</span></span>
        <span className="text-slate-400">Boş: <span className="text-green-400 font-medium">{unit === 'GB' ? fmtDisk(free) : fmtMem(free)}</span></span>
      </div>
    </div>
  )
}

// ── VM Status Pie ───────────────────────────────────────────────────────────
const VMStatusPie = ({ poweredOn, poweredOff }: { poweredOn: number; poweredOff: number }) => {
  const total = poweredOn + poweredOff
  if (total === 0) return null
  
  const data = [
    { name: 'Çalışan', value: poweredOn, color: NEON.green },
    { name: 'Kapalı', value: poweredOff, color: '#475569' },
  ].filter(d => d.value > 0)

  return (
    <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-5">
      <h3 className="text-sm font-medium text-white mb-4">VM Durum Dağılımı</h3>
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
              <span className="text-sm text-slate-300">Çalışan</span>
            </div>
            <span className="text-sm font-bold text-green-400">{poweredOn}</span>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <PowerOff className="w-4 h-4 text-slate-500" />
              <span className="text-sm text-slate-300">Kapalı</span>
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
  if (hosts.length === 0) return null

  const data = hosts.slice(0, 6).map(h => ({
    name: h.host_name.length > 12 ? h.host_name.slice(0, 12) + '...' : h.host_name,
    CPU: h.cpu_usage_pct || 0,
    RAM: h.mem_usage_pct || 0,
    Disk: h.ds_usage_pct || 0,
  }))

  return (
    <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-5">
      <h3 className="text-sm font-medium text-white mb-4">Host Kaynak Kullanımı</h3>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} layout="vertical" margin={{ left: 0, right: 10 }}>
          <XAxis type="number" domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} width={80} axisLine={false} tickLine={false} />
          <Tooltip 
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
            formatter={(v: number) => [`${v}%`, '']}
          />
          <Bar dataKey="CPU" fill={NEON.cyan} radius={[0, 4, 4, 0]} barSize={8} />
          <Bar dataKey="RAM" fill={NEON.purple} radius={[0, 4, 4, 0]} barSize={8} />
          <Bar dataKey="Disk" fill={NEON.orange} radius={[0, 4, 4, 0]} barSize={8} />
        </BarChart>
      </ResponsiveContainer>
      <div className="flex justify-center gap-4 mt-2">
        {[{ label: 'CPU', color: NEON.cyan }, { label: 'RAM', color: NEON.purple }, { label: 'Disk', color: NEON.orange }].map(l => (
          <div key={l.label} className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full" style={{ background: l.color }} />
            <span className="text-xs text-slate-400">{l.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── VM Table ────────────────────────────────────────────────────────────────
const VMTable = ({ vms, hypervisors }: { vms: VM[]; hypervisors: Hypervisor[] }) => {
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'online' | 'offline'>('all')
  const [sortBy, setSortBy] = useState<'name' | 'cpu' | 'ram'>('name')

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
      list = list.filter(v => v.status === 'ONLINE' || v.vm_power_state?.toLowerCase().includes('on'))
    } else if (filter === 'offline') {
      list = list.filter(v => v.status === 'OFFLINE' || v.vm_power_state?.toLowerCase().includes('off'))
    }
    
    if (sortBy === 'cpu') list.sort((a, b) => (b.cpu_cores || 0) - (a.cpu_cores || 0))
    else if (sortBy === 'ram') list.sort((a, b) => (b.memory_gb || 0) - (a.memory_gb || 0))
    else list.sort((a, b) => a.name.localeCompare(b.name))
    
    return list
  }, [vms, search, filter, sortBy])

  const isPoweredOn = (vm: VM) => vm.status === 'ONLINE' || vm.vm_power_state?.toLowerCase().includes('on')

  return (
    <div className="bg-cyber-card rounded-xl border border-white/[0.06] overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 border-b border-white/[0.06] flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Monitor className="w-5 h-5 text-blue-400" />
          <span className="text-sm font-medium text-white">Sanal Makineler</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-400">{vms.length}</span>
        </div>
        <div className="flex items-center gap-2">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              placeholder="VM ara..."
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
            <option value="all">Tümü</option>
            <option value="online">Çalışan</option>
            <option value="offline">Kapalı</option>
          </select>
          {/* Sort */}
          <select
            value={sortBy}
            onChange={e => setSortBy(e.target.value as any)}
            className="bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500/50"
          >
            <option value="name">İsme Göre</option>
            <option value="cpu">CPU'ya Göre</option>
            <option value="ram">RAM'e Göre</option>
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
              <th className="text-center px-5 py-3 font-medium">RAM</th>
              <th className="text-center px-5 py-3 font-medium">Durum</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.04]">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-5 py-12 text-center text-slate-500">
                  {search || filter !== 'all' ? 'Filtreye uygun VM bulunamadı' : 'Henüz VM yok'}
                </td>
              </tr>
            ) : (
              filtered.slice(0, 100).map(vm => (
                <tr key={vm.id} className="hover:bg-white/[0.02] transition-colors">
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${isPoweredOn(vm) ? 'bg-green-500/15' : 'bg-slate-700/50'}`}>
                        <Server className={`w-4 h-4 ${isPoweredOn(vm) ? 'text-green-400' : 'text-slate-500'}`} />
                      </div>
                      <div>
                        <div className="text-sm font-medium text-white">{vm.name}</div>
                        {vm.ai_ready && <span className="text-[10px] text-cyan-400">AI Ready</span>}
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
                      {isPoweredOn(vm) ? 'Çalışıyor' : 'Kapalı'}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {filtered.length > 100 && (
          <div className="px-5 py-3 text-center text-xs text-slate-500 border-t border-white/[0.04]">
            İlk 100 VM gösteriliyor. Toplam: {filtered.length}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Host Cards ──────────────────────────────────────────────────────────────
const HostCard = ({ host, hvName }: { host: EsxHost; hvName: string }) => {
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
            <div className="text-xs text-slate-500">{hvName} • {host.vms_running}/{host.vms_total} VM</div>
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
              <div className="text-[10px] text-slate-500">RAM</div>
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
            { label: 'RAM', used: host.mem_used_mb, total: host.mem_total_mb, unit: 'MB', pct: host.mem_usage_pct, color: NEON.purple },
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
              {host.inventory.vendor && <div><span className="text-slate-500">Marka:</span> <span className="text-slate-300">{host.inventory.vendor}</span></div>}
              {host.inventory.model && <div><span className="text-slate-500">Model:</span> <span className="text-slate-300">{host.inventory.model}</span></div>}
              {host.inventory.cpu_model && <div className="col-span-2"><span className="text-slate-500">CPU:</span> <span className="text-slate-300">{host.inventory.cpu_model}</span></div>}
              <div><span className="text-slate-500">Core:</span> <span className="text-slate-300">{host.cpu_cores}</span></div>
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
  syncingAll = false,
  readOnly = false,
}: { 
  hypervisors: Hypervisor[]
  onAdd: () => void
  onDelete: (id: number) => void
  onSync: (id: number) => void
  onSyncAll?: () => void
  syncingAll?: boolean
  readOnly?: boolean
}) => {
  const getTypeColor = (type: string) => {
    const colors: Record<string, string> = {
      vmware: 'from-green-500 to-green-600',
      hyperv: 'from-blue-500 to-blue-600',
      kvm: 'from-orange-500 to-orange-600',
      xen: 'from-blue-600 to-blue-700',
      proxmox: 'from-red-500 to-red-600',
    }
    return colors[type.toLowerCase()] || 'from-slate-500 to-slate-600'
  }

  const getTypeLabel = (type: string) => {
    const labels: Record<string, string> = { vmware: 'VMware', hyperv: 'Hyper-V', kvm: 'oVirt/KVM', xen: 'XEN', proxmox: 'Proxmox' }
    return labels[type.toLowerCase()] || type.toUpperCase()
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-white">Hypervisor Bağlantıları</h3>
          {!readOnly && (
            <p className="text-xs text-slate-500 mt-0.5">Envanter otomatik olarak her 5 dakikada bir senkronize edilir</p>
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
                <RefreshCw className={`w-4 h-4 ${syncingAll ? 'animate-spin' : ''}`} /> Tümünü Senkronize Et
              </button>
            )}
            <button
              onClick={onAdd}
              className="flex items-center gap-2 px-3 py-1.5 bg-gradient-to-r from-blue-600 to-blue-700 text-white text-sm rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all"
            >
              <Plus className="w-4 h-4" /> Ekle
            </button>
          </div>
        )}
      </div>

      {hypervisors.length === 0 ? (
        <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-12 text-center">
          <Database className="w-12 h-12 text-slate-600 mx-auto mb-3" />
          <p className="text-slate-400 mb-4">Henüz hypervisor bağlantısı yok</p>
          {readOnly ? (
            <Link to="/integrations/hypervisors" className="text-blue-400 hover:text-blue-300 text-sm">
              Entegrasyonlar → vCenter / OLVM
            </Link>
          ) : (
            <button onClick={onAdd} className="text-blue-400 hover:text-blue-300 text-sm">+ Hypervisor Ekle</button>
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
                    <div className="text-sm font-medium text-white">{hv.name}</div>
                    <div className="text-xs text-slate-500">{getTypeLabel(hv.type)}</div>
                  </div>
                </div>
              </div>
              <div className="space-y-1.5 text-xs mb-4">
                <div className="flex"><span className="w-12 text-slate-500">IP:</span><span className="text-slate-300 font-mono">{hv.ip_address}:{hv.port}</span></div>
                <div className="flex"><span className="w-12 text-slate-500">User:</span><span className="text-slate-300">{hv.username}</span></div>
              </div>
              {!readOnly && (
                <div className="flex gap-2">
                  <button
                    onClick={() => onSync(hv.id)}
                    className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-blue-500/10 text-blue-400 rounded-lg hover:bg-blue-500/20 text-xs transition-colors"
                  >
                    <RefreshCw className="w-3.5 h-3.5" /> Sync VMs
                  </button>
                  <button
                    onClick={() => onDelete(hv.id)}
                    className="px-3 py-2 bg-red-500/10 text-red-400 rounded-lg hover:bg-red-500/20 text-xs transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
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
  onDone,
  onDismiss,
}: {
  hypervisorId: number
  hypervisorName: string
  onDone: (job: SyncJob) => void
  onDismiss: () => void
}) => {
  const [job, setJob] = useState<SyncJob>({ status: 'running', percent: 1, message: 'Tarama başlıyor...' })
  const [vmCount, setVmCount] = useState(0)

  const onDoneRef = React.useRef(onDone)
  onDoneRef.current = onDone

  useEffect(() => {
    let cancelled = false
    let finished = false
    const tick = async () => {
      if (finished || cancelled) return
      try {
        const r = await fetch(`${API_BASE_URL}/hypervisors/${hypervisorId}/sync-status`, {
          headers: inventoryHeaders(),
        })
        if (!r.ok || cancelled) return
        const data = await r.json()
        const j: SyncJob = data.sync_job || {}
        setJob(j)
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
              {job.status === 'done' ? 'Tarama tamamlandı' : job.status === 'error' ? 'Tarama hatası' : 'VM envanteri taranıyor'}
            </h2>
            <p className="text-sm text-slate-400 mt-0.5 truncate">{hypervisorName}</p>
          </div>
        </div>

        <div className="mb-4">
          <div className="flex justify-between text-xs text-slate-400 mb-1.5">
            <span>{job.message || 'İşleniyor...'}</span>
            <span className="font-mono text-slate-300">{pct}%</span>
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

        <div className="grid grid-cols-2 gap-3 mb-5">
          <div className="bg-slate-800/60 rounded-lg px-3 py-2.5 border border-white/[0.04]">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">İlerleme</div>
            <div className="text-sm text-white font-medium mt-0.5">
              {job.vms_done != null && job.vms_total != null
                ? `${job.vms_done} / ${job.vms_total}`
                : '—'}
            </div>
          </div>
          <div className="bg-slate-800/60 rounded-lg px-3 py-2.5 border border-white/[0.04]">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">DB'de VM</div>
            <div className="text-sm text-white font-medium mt-0.5">{vmCount}</div>
          </div>
        </div>

        {!done && (
          <p className="text-xs text-slate-500 mb-4 leading-relaxed">
            İlk tam tarama büyük ortamlarda 15–20 dakika sürebilir. Bu pencereyi kapatabilirsiniz;
            Sync VMs ile durumu izlemeye devam edebilirsiniz.
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
            {done ? 'Kapat' : 'Arka planda devam et'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Add Hypervisor Modal ────────────────────────────────────────────────────
const AddHypervisorModal = ({ onClose, onCreate }: { onClose: () => void; onCreate: (data: any) => void }) => {
  const [formData, setFormData] = useState({
    name: '', type: 'vmware', hostname: '', ip_address: '', port: 443, username: '', password: ''
  })
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const testConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const r = await fetch(`${API_BASE_URL}/hypervisors/test-connection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: formData.type, hostname: formData.hostname || formData.ip_address, ip_address: formData.ip_address, port: formData.port, username: formData.username, password: formData.password })
      })
      const data = await r.json()
      setTestResult({ success: data.success, message: data.message })
    } catch {
      setTestResult({ success: false, message: 'Bağlantı hatası' })
    } finally {
      setTesting(false)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!testResult?.success) return
    onCreate(formData)
    onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-cyber-card rounded-2xl border border-white/[0.06] w-full max-w-md shadow-2xl">
        <div className="px-6 py-4 border-b border-white/[0.06] flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Hypervisor Ekle</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Adı *</label>
            <input type="text" required value={formData.name} onChange={e => { setFormData({...formData, name: e.target.value}); setTestResult(null) }}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50" placeholder="vCenter Production" />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Tip *</label>
            <select value={formData.type} onChange={e => { setFormData({...formData, type: e.target.value}); setTestResult(null) }}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50">
              <option value="vmware">VMware vCenter / ESXi</option>
              <option value="hyperv">Microsoft Hyper-V</option>
              <option value="kvm">KVM / oVirt</option>
              <option value="proxmox">Proxmox VE</option>
            </select>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <label className="block text-xs text-slate-400 mb-1.5">IP Adresi *</label>
              <input type="text" required value={formData.ip_address} onChange={e => { setFormData({...formData, ip_address: e.target.value}); setTestResult(null) }}
                className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50" placeholder="192.168.1.100" />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Port</label>
              <input type="number" value={formData.port} onChange={e => { setFormData({...formData, port: parseInt(e.target.value) || 443}); setTestResult(null) }}
                className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50" />
            </div>
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Kullanıcı Adı *</label>
            <input type="text" required value={formData.username} onChange={e => { setFormData({...formData, username: e.target.value}); setTestResult(null) }}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50" placeholder="administrator@vsphere.local" />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Şifre *</label>
            <input type="password" required value={formData.password} onChange={e => { setFormData({...formData, password: e.target.value}); setTestResult(null) }}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50" />
          </div>

          <button type="button" onClick={testConnection} disabled={testing || !formData.username || !formData.password}
            className="w-full py-2.5 bg-blue-600/20 text-blue-400 border border-blue-500/30 rounded-lg hover:bg-blue-600/30 disabled:opacity-50 text-sm font-medium flex items-center justify-center gap-2">
            {testing ? <><RefreshCw className="w-4 h-4 animate-spin" /> Test Ediliyor...</> : 'Bağlantıyı Test Et'}
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
            <button type="button" onClick={onClose} className="flex-1 px-4 py-2.5 bg-white/[0.07] text-white rounded-lg hover:bg-slate-600 text-sm">İptal</button>
            <button type="submit" disabled={!testResult?.success}
              className="flex-1 px-4 py-2.5 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 disabled:opacity-50 text-sm font-medium">
              Ekle
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
  const [activeTab, setActiveTab] = useState<'dashboard' | 'vms' | 'hosts' | 'hypervisors'>(allowInventoryEdit ? 'hypervisors' : 'dashboard')
  const [showAddModal, setShowAddModal] = useState(false)
  const [scanTarget, setScanTarget] = useState<{ id: number; name: string } | null>(null)
  const [confirmState, setConfirmState] = useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const showConfirm = (msg: string): Promise<boolean> => new Promise(resolve => setConfirmState({ msg, resolve }))
  const queryClient = useQueryClient()

  // Hypervisors — dashboard'un güncel kalması için periyodik olarak yenilenir
  // (backend'deki otomatik envanter senkronizasyonu her 5 dakikada bir çalışır)
  const { data: hypervisors = [], isLoading: hvLoading } = useQuery<Hypervisor[]>({
    queryKey: ['hypervisors'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/`)
      if (!r.ok) throw new Error('Hypervisor listesi alınamadı')
      return r.json()
    },
    refetchInterval: 60_000,
  })

  // VMs — backend ile aynı tanım: hypervisor_id dolu OLUŞTU ya da server_type=VIRTUAL
  // (OLVM/UCMDB gibi kaynaklardan hypervisor bağlantısı olmadan gelen VM'ler de dahil)
  const { data: vms = [] } = useQuery<VM[]>({
    queryKey: ['servers', 'platform=virt'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/servers/?platform=virt`)
      if (!r.ok) return []
      return r.json()
    },
    refetchInterval: 60_000,
  })

  // ESX Host Metrics
  const [allHosts, setAllHosts] = useState<{ hvName: string; host: EsxHost }[]>([])
  const [hostsLoading, setHostsLoading] = useState(true)

  useEffect(() => {
    const vmwareHvs = hypervisors.filter(h => h.type?.toLowerCase() === 'vmware')
    if (vmwareHvs.length === 0) { setHostsLoading(false); return }

    Promise.all(
      vmwareHvs.map(hv =>
        fetch(`${API_BASE_URL}/hypervisors/${hv.id}/host-metrics`)
          .then(r => r.ok ? r.json() : null)
          .then(data => (data?.hosts || []).map((h: EsxHost) => ({ hvName: hv.name, host: h })))
          .catch(() => [])
      )
    ).then(results => {
      setAllHosts(results.flat())
      setHostsLoading(false)
    })
  }, [hypervisors])

  // Mutations
  const startScan = async (id: number, name: string) => {
    const r = await fetch(`${API_BASE_URL}/hypervisors/${id}/sync-vms?background=true`, {
      method: 'POST',
      headers: inventoryHeaders(),
    })
    if (!r.ok) throw new Error((await r.json()).detail || 'Sync başlatılamadı')
    setScanTarget({ id, name })
    return r.json()
  }

  const createMutation = useMutation({
    mutationFn: async (data: any) => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/`, {
        method: 'POST',
        headers: inventoryHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(data),
      })
      if (!r.ok) throw new Error((await r.json()).detail || 'Ekleme hatası')
      return r.json()
    },
    onSuccess: async (created) => {
      queryClient.invalidateQueries({ queryKey: ['hypervisors'] })
      try {
        await startScan(created.id, created.name)
      } catch (e) {
        alert(e instanceof Error ? e.message : 'Tarama başlatılamadı')
      }
    },
    onError: (e) => alert(e instanceof Error ? e.message : 'Ekleme hatası'),
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/${id}`, { method: 'DELETE', headers: inventoryHeaders() })
      if (!r.ok) throw new Error('Silme hatası')
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
    onError: (e) => alert(e instanceof Error ? e.message : 'Sync hatası'),
  })

  const syncAllMutation = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/sync-all-vms`, { method: 'POST', headers: inventoryHeaders() })
      if (!r.ok) throw new Error((await r.json()).detail || 'Sync hatası')
      return r.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['servers'] })
      queryClient.invalidateQueries({ queryKey: ['hypervisors'] })
      alert(`Tüm hypervisor'lar senkronize edildi. Toplam ${data.total_synced} yeni VM eklendi.`)
    },
    onError: (e) => alert(e instanceof Error ? e.message : 'Senkronizasyon hatası')
  })

  // Stats
  const poweredOn = vms.filter(v => v.status === 'ONLINE' || v.vm_power_state?.toLowerCase().includes('on')).length
  const poweredOff = vms.length - poweredOn
  const totalVmCpu = vms.reduce((acc, v) => acc + (v.cpu_cores || 0), 0)
  const totalVmRam = vms.reduce((acc, v) => acc + (v.memory_gb || 0), 0)

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
          onDone={() => {
            queryClient.invalidateQueries({ queryKey: ['servers'] })
            queryClient.invalidateQueries({ queryKey: ['hypervisors'] })
          }}
          onDismiss={() => {
            setScanTarget(null)
            queryClient.invalidateQueries({ queryKey: ['servers'] })
            queryClient.invalidateQueries({ queryKey: ['hypervisors'] })
          }}
        />
      )}

      <div className="space-y-6">
        <div>
          {allowInventoryEdit ? (
            <>
              <Link to="/integrations" className="text-xs text-slate-500 hover:text-white">← Envanter Merkezi</Link>
              <h1 className="text-xl font-bold text-white mt-1">vCenter / OLVM — Hypervisor Yönetimi</h1>
              <p className="text-sm text-slate-500">Hypervisor bağlantıları ve VM envanter senkronizasyonu</p>
            </>
          ) : (
            <>
              <h1 className="text-xl font-bold text-white">Sanallaştırma Dashboard</h1>
              <p className="text-sm text-slate-500">Hypervisor, host ve VM operasyon görünümü</p>
              <Link to="/integrations/hypervisors" className="inline-block mt-2 text-xs text-blue-400 hover:text-blue-300">
                Envanter yönetimi → Entegrasyonlar
              </Link>
            </>
          )}
        </div>
        {!allowInventoryEdit && (
          <>
            {/* Quick Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
              <StatCard icon={Database} label="Hypervisor" value={hypervisors.length} sub={`${hypervisors.filter(h => h.type === 'vmware').length} VMware`} accent={NEON.blue} />
              <StatCard icon={Server} label="Host" value={allHosts.length} sub="ESX/KVM" accent={NEON.cyan} />
              <StatCard icon={Monitor} label="Toplam VM" value={vms.length} sub={`${poweredOn} çalışıyor`} accent={NEON.purple} />
              <StatCard icon={Power} label="Aktif VM" value={poweredOn} sub={`${poweredOff} kapalı`} accent={NEON.green} />
              <StatCard icon={Cpu} label="vCPU Tahsis" value={totalVmCpu} sub="toplam çekirdek" accent={NEON.orange} />
              <StatCard icon={MemoryStick} label="RAM Tahsis" value={`${totalVmRam} GB`} sub="toplam bellek" accent={NEON.red} />
            </div>

            <div className="flex justify-end">
              <Link
                to="/infra-reports"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm border border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 transition-colors"
              >
                <BarChart3 className="w-4 h-4" />
                Altyapı Raporları
              </Link>
            </div>
          </>
        )}

        {/* Tabs */}
        <div className="flex gap-1 p-1 bg-cyber-card rounded-xl border border-white/[0.06] w-fit">
          {(allowInventoryEdit
            ? [{ id: 'hypervisors', icon: Settings, label: 'Hypervisorlar' }]
            : [
                { id: 'dashboard', icon: LayoutDashboard, label: 'Dashboard' },
                { id: 'vms', icon: Monitor, label: 'VM Listesi' },
                { id: 'hosts', icon: Database, label: 'Host\'lar' },
                { id: 'hypervisors', icon: Settings, label: 'Hypervisorlar' },
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
                <ResourceGauge label="CPU Kullanımı" used={usedHostCpu} total={totalHostCpu} unit="MHz" accent={NEON.cyan} />
                <ResourceGauge label="Bellek Kullanımı" used={usedHostMem} total={totalHostMem} unit="MB" accent={NEON.purple} />
                <ResourceGauge label="Depolama Kullanımı" used={usedHostDisk} total={totalHostDisk} unit="GB" accent={NEON.orange} />
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
                  <h3 className="text-sm font-medium text-white">Son Eklenen VM'ler</h3>
                  <button onClick={() => setActiveTab('vms')} className="text-xs text-blue-400 hover:text-blue-300">Tümünü Gör →</button>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                  {vms.slice(0, 8).map(vm => {
                    const isOn = vm.status === 'ONLINE' || vm.vm_power_state?.toLowerCase().includes('on')
                    return (
                      <div key={vm.id} className="flex items-center gap-3 p-3 bg-slate-800/50 rounded-lg">
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${isOn ? 'bg-green-500/15' : 'bg-slate-700'}`}>
                          <Server className={`w-4 h-4 ${isOn ? 'text-green-400' : 'text-slate-500'}`} />
                        </div>
                        <div className="min-w-0">
                          <div className="text-sm text-white truncate">{vm.name}</div>
                          <div className="text-xs text-slate-500">{vm.cpu_cores} vCPU • {vm.memory_gb} GB</div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {!allowInventoryEdit && activeTab === 'vms' && <VMTable vms={vms} hypervisors={hypervisors} />}

        {!allowInventoryEdit && activeTab === 'hosts' && (
          <div className="space-y-4">
            {hostsLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="w-8 h-8 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
              </div>
            ) : allHosts.length === 0 ? (
              <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-12 text-center">
                <Database className="w-12 h-12 text-slate-600 mx-auto mb-3" />
                <p className="text-slate-400">Host verisi bulunamadı</p>
                <p className="text-xs text-slate-500 mt-1">
                  {allowInventoryEdit ? 'VMware hypervisor ekleyip sync yapın' : 'Entegrasyonlar üzerinden hypervisor tanımlayın'}
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
              if (await showConfirm('Bu hypervisor\'ı silmek istediğinize emin misiniz?')) {
                deleteMutation.mutate(id)
              }
            }}
            onSync={(id) => syncMutation.mutate(id)}
            onSyncAll={() => syncAllMutation.mutate()}
            syncingAll={syncAllMutation.isPending}
          />
        )}
      </div>
    </>
  )
}

export default Hypervisors
