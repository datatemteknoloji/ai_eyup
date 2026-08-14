/**
 * Exadata Dashboard — rack/kabinet görünümü: compute node ve storage cell aynı kabinette.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Database, Server, HardDrive, Plus, RefreshCw, ChevronDown, ChevronRight,
  Cpu, CheckCircle2, X, Zap,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { inventoryHeaders } from '../lib/inventoryApi'
import { useT, useLocale } from '../i18n/LocaleProvider'

interface ExadataNode {
  id: number; rack_id: number; role: string; name: string
  hostname?: string; ip_address?: string; ilom_ip?: string
  status?: string; position_in_rack?: string
  cpu_cores?: number; memory_gb?: number; storage_tb?: number
  server_id?: number | null
}

interface ExadataCabinet {
  id: number; name: string; rack_name?: string; model?: string
  datacenter?: string; cabinet_label?: string; status?: string
  health: string; compute_count: number; cell_count: number
  compute_nodes: ExadataNode[]; storage_cells: ExadataNode[]
  other_nodes?: ExadataNode[]
  last_sync?: string | null
}

const HEALTH_STYLE: Record<string, { bg: string; border: string; text: string; dot: string }> = {
  healthy:  { bg: 'bg-green-500/10',  border: 'border-green-500/30',  text: 'text-green-400',  dot: 'bg-green-400' },
  warning:  { bg: 'bg-amber-500/10',  border: 'border-amber-500/30',  text: 'text-amber-400',  dot: 'bg-amber-400' },
  critical: { bg: 'bg-red-500/10',    border: 'border-red-500/30',    text: 'text-red-400',    dot: 'bg-red-400' },
  unknown:  { bg: 'bg-slate-500/10',  border: 'border-slate-600/40',  text: 'text-slate-400',  dot: 'bg-slate-500' },
}

function statusColor(status?: string) {
  const s = (status || 'unknown').toUpperCase()
  if (['ONLINE', 'OK', 'UP', 'RUNNING'].includes(s)) return 'text-green-400'
  if (['WARNING', 'DEGRADED'].includes(s)) return 'text-amber-400'
  if (['OFFLINE', 'CRITICAL', 'DOWN', 'FAILED'].includes(s)) return 'text-red-400'
  return 'text-slate-500'
}

function NodeTile({ node, variant }: { node: ExadataNode; variant: 'compute' | 'cell' }) {
  const t = useT()
  const accent = variant === 'compute' ? 'border-cyan-500/25 bg-cyan-500/5' : 'border-orange-500/25 bg-orange-500/5'
  const Icon = variant === 'compute' ? Cpu : HardDrive
  return (
    <div className={`rounded-lg border p-3 ${accent} hover:border-opacity-60 transition-colors`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Icon size={14} className={variant === 'compute' ? 'text-cyan-400 flex-shrink-0' : 'text-orange-400 flex-shrink-0'} />
          <div className="min-w-0">
            <div className="text-sm font-medium text-white truncate">{node.name}</div>
            <div className="text-[10px] text-slate-500 truncate">{node.ip_address || node.hostname || '—'}</div>
          </div>
        </div>
        <span className={`text-[10px] font-medium ${statusColor(node.status)}`}>{node.status || '?'}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-500">
        {node.position_in_rack && <span>{t('exa_u_pos', { n: node.position_in_rack })}</span>}
        {node.cpu_cores != null && variant === 'compute' && <span>{node.cpu_cores} CPU</span>}
        {node.memory_gb != null && variant === 'compute' && <span>{t('exa_gb_memory', { n: node.memory_gb })}</span>}
        {node.storage_tb != null && variant === 'cell' && <span>{node.storage_tb} TB</span>}
        {node.server_id && (
          <Link to={`/servers?id=${node.server_id}`} className="text-cyan-500 hover:text-cyan-400">{t('exa_linux_n', { id: node.server_id })}</Link>
        )}
      </div>
    </div>
  )
}

function CabinetCard({ cabinet, onSync, showSync = true }: { cabinet: ExadataCabinet; onSync: (id: number) => void; showSync?: boolean }) {
  const t = useT()
  const { locale } = useLocale()
  const [open, setOpen] = useState(true)
  const hs = HEALTH_STYLE[cabinet.health] || HEALTH_STYLE.unknown

  return (
    <div className={`rounded-2xl border overflow-hidden ${hs.border} ${hs.bg}`}>
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-white/[0.02] transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          {open ? <ChevronDown size={16} className="text-slate-500" /> : <ChevronRight size={16} className="text-slate-500" />}
          <div className={`w-2.5 h-2.5 rounded-full ${hs.dot}`} />
          <div>
            <div className="text-white font-semibold">{cabinet.name}</div>
            <div className="text-xs text-slate-500 mt-0.5">
              {[cabinet.model, cabinet.datacenter, cabinet.cabinet_label].filter(Boolean).join(' · ') || t('exa_rack')}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right text-xs">
            <span className="text-cyan-400">{t('exa_cn', { n: cabinet.compute_count })}</span>
            <span className="text-slate-600 mx-1">|</span>
            <span className="text-orange-400">{t('exa_cell', { n: cabinet.cell_count })}</span>
          </div>
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${hs.border} ${hs.text}`}>
            {cabinet.health === 'healthy' ? t('exa_healthy') : cabinet.health === 'warning' ? t('status_warning') : cabinet.health === 'critical' ? t('status_critical') : t('exa_unknown')}
          </span>
          {showSync && (
            <button
              type="button"
              onClick={e => { e.stopPropagation(); onSync(cabinet.id) }}
              className="p-1.5 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
              title={t('exa_sync_title')}
            >
              <RefreshCw size={14} />
            </button>
          )}
        </div>
      </button>

      {open && (
        <div className="px-5 pb-5">
          {/* Kabinet görseli — compute sol, cell sağ */}
          <div className="relative rounded-xl border-2 border-dashed border-slate-600/50 bg-slate-900/40 p-4">
            <div className="absolute top-2 left-1/2 -translate-x-1/2 text-[10px] uppercase tracking-widest text-slate-600 font-semibold">
              {cabinet.cabinet_label || cabinet.rack_name || t('exa_cabinet')}
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <Server size={14} className="text-cyan-400" />
                  <span className="text-xs font-semibold text-cyan-300 uppercase tracking-wide">{t('exa_compute_nodes')}</span>
                </div>
                {cabinet.compute_nodes.length === 0 ? (
                  <div className="text-xs text-slate-600 py-6 text-center border border-dashed border-slate-700 rounded-lg">{t('exa_no_compute')}</div>
                ) : (
                  <div className="space-y-2">
                    {cabinet.compute_nodes.map(n => <NodeTile key={n.id} node={n} variant="compute" />)}
                  </div>
                )}
              </div>
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <HardDrive size={14} className="text-orange-400" />
                  <span className="text-xs font-semibold text-orange-300 uppercase tracking-wide">{t('exa_storage_cells')}</span>
                </div>
                {cabinet.storage_cells.length === 0 ? (
                  <div className="text-xs text-slate-600 py-6 text-center border border-dashed border-slate-700 rounded-lg">{t('exa_no_cell')}</div>
                ) : (
                  <div className="space-y-2">
                    {cabinet.storage_cells.map(n => <NodeTile key={n.id} node={n} variant="cell" />)}
                  </div>
                )}
              </div>
            </div>
          </div>
          {cabinet.last_sync && (
            <div className="text-[10px] text-slate-600 mt-2">{t('exa_last_sync', { time: new Date(cabinet.last_sync).toLocaleString(locale === 'en' ? 'en-US' : 'tr-TR') })}</div>
          )}
        </div>
      )}
    </div>
  )
}

export default function ExadataDashboard({ allowInventoryEdit = false }: { allowInventoryEdit?: boolean }) {
  const t = useT()
  const qc = useQueryClient()
  const [showAddRack, setShowAddRack] = useState(false)
  const [addNodeRackId, setAddNodeRackId] = useState<number | null>(null)
  const [rackForm, setRackForm] = useState({ name: '', model: '', datacenter: '', cabinet_label: '' })
  const [nodeForm, setNodeForm] = useState({ role: 'compute_node', name: '', ip_address: '', cpu_cores: '', memory_gb: '', storage_tb: '' })

  const { data, isLoading, refetch } = useQuery<{ cabinets: ExadataCabinet[]; total_racks: number; total_compute_nodes: number; total_storage_cells: number }>({
    queryKey: ['exadata-cabinets'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/exadata/cabinets`)
      if (!r.ok) throw new Error('cabinet fetch failed')
      return r.json()
    },
    refetchInterval: 60_000,
  })

  const createRack = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${API_BASE_URL}/exadata/racks`, {
        method: 'POST', headers: inventoryHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(rackForm),
      })
      if (!r.ok) throw new Error('create failed')
      return r.json()
    },
    onSuccess: () => { setShowAddRack(false); setRackForm({ name: '', model: '', datacenter: '', cabinet_label: '' }); qc.invalidateQueries({ queryKey: ['exadata-cabinets'] }) },
  })

  const addNode = useMutation({
    mutationFn: async () => {
      if (!addNodeRackId) return
      const r = await fetch(`${API_BASE_URL}/exadata/racks/${addNodeRackId}/nodes`, {
        method: 'POST', headers: inventoryHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          role: nodeForm.role,
          name: nodeForm.name,
          ip_address: nodeForm.ip_address || undefined,
          cpu_cores: nodeForm.cpu_cores ? Number(nodeForm.cpu_cores) : undefined,
          memory_gb: nodeForm.memory_gb ? Number(nodeForm.memory_gb) : undefined,
          storage_tb: nodeForm.storage_tb ? Number(nodeForm.storage_tb) : undefined,
          status: 'unknown',
        }),
      })
      if (!r.ok) throw new Error('add node failed')
      return r.json()
    },
    onSuccess: () => {
      setAddNodeRackId(null)
      setNodeForm({ role: 'compute_node', name: '', ip_address: '', cpu_cores: '', memory_gb: '', storage_tb: '' })
      qc.invalidateQueries({ queryKey: ['exadata-cabinets'] })
    },
  })

  const syncRack = useMutation({
    mutationFn: async (rackId: number) => {
      const r = await fetch(`${API_BASE_URL}/exadata/racks/${rackId}/sync`, { method: 'POST', headers: inventoryHeaders() })
      if (!r.ok) throw new Error('sync failed')
      return r.json()
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['exadata-cabinets'] }),
  })

  const cabinets = data?.cabinets || []

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-orange-500/15 border border-orange-500/30 flex items-center justify-center">
            <Database size={20} className="text-orange-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">{t('exa_title')}</h1>
            <p className="text-slate-400 text-sm">
              {allowInventoryEdit
                ? t('exa_sub_edit')
                : t('exa_sub_view')}
            </p>
            {!allowInventoryEdit && (
              <Link to="/integrations/exadata" className="text-xs text-orange-400 hover:text-orange-300 mt-1 inline-block">
                {t('exa_add_inventory')}
              </Link>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => refetch()} className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200">
            <RefreshCw size={12} /> {t('refresh_action')}
          </button>
          {allowInventoryEdit && (
            <button onClick={() => setShowAddRack(true)} className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-orange-600 hover:bg-orange-500 text-white font-medium">
              <Plus size={12} /> {t('exa_add_rack')}
            </button>
          )}
          <Link to="/exadata/ops" className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:text-white">
            <Zap size={12} /> {t('nav_command_center')}
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: t('exa_stat_rack'), value: data?.total_racks ?? 0, icon: Database, color: 'text-orange-400' },
          { label: t('exa_stat_cn'), value: data?.total_compute_nodes ?? 0, icon: Server, color: 'text-cyan-400' },
          { label: t('exa_stat_cell'), value: data?.total_storage_cells ?? 0, icon: HardDrive, color: 'text-amber-400' },
          { label: t('exa_stat_healthy'), value: cabinets.filter(c => c.health === 'healthy').length, icon: CheckCircle2, color: 'text-green-400' },
        ].map(k => (
          <div key={k.label} className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <k.icon size={18} className={`${k.color} mb-2`} />
            <div className="text-2xl font-bold text-white">{k.value}</div>
            <div className="text-xs text-slate-500">{k.label}</div>
          </div>
        ))}
      </div>

      {isLoading ? (
        <div className="text-center py-16 text-slate-500 text-sm">{t('exa_loading')}</div>
      ) : cabinets.length === 0 ? (
        <div className="text-center py-20 border border-dashed border-slate-700 rounded-2xl">
          <Database size={40} className="mx-auto text-slate-600 mb-3" />
          <p className="text-slate-400 mb-4">{t('exa_empty')}</p>
          {allowInventoryEdit ? (
            <button onClick={() => setShowAddRack(true)} className="text-sm px-4 py-2 rounded-lg bg-orange-600 hover:bg-orange-500 text-white">
              {t('exa_first_rack')}
            </button>
          ) : (
            <Link to="/integrations/exadata" className="text-sm px-4 py-2 rounded-lg bg-orange-600/20 border border-orange-500/30 text-orange-300 hover:text-white inline-block">
              {t('exa_integrations')}
            </Link>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          {cabinets.map(c => (
            <div key={c.id}>
              <CabinetCard cabinet={c} onSync={id => syncRack.mutate(id)} showSync={allowInventoryEdit} />
              {allowInventoryEdit && (
                <button
                  onClick={() => { setAddNodeRackId(c.id); setNodeForm({ role: 'compute_node', name: '', ip_address: '', cpu_cores: '', memory_gb: '', storage_tb: '' }) }}
                  className="mt-1 text-[11px] text-slate-500 hover:text-orange-400 flex items-center gap-1"
                >
                  <Plus size={11} /> {t('exa_add_node', { name: c.name })}
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {allowInventoryEdit && showAddRack && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold">{t('exa_new_rack')}</h3>
              <button onClick={() => setShowAddRack(false)} className="text-slate-500 hover:text-white"><X size={18} /></button>
            </div>
            <div className="space-y-3">
              {(['name', 'model', 'datacenter', 'cabinet_label'] as const).map(f => (
                <div key={f}>
                  <label className="text-xs text-slate-500 block mb-1">{f === 'name' ? t('exa_name_req') : f === 'model' ? t('exa_model') : f === 'datacenter' ? t('exa_dc') : t('exa_cabinet_label')}</label>
                  <input
                    value={rackForm[f]}
                    onChange={e => setRackForm(p => ({ ...p, [f]: e.target.value }))}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
                    placeholder={f}
                  />
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button onClick={() => setShowAddRack(false)} className="px-4 py-2 text-sm text-slate-400">{t('cancel')}</button>
              <button
                onClick={() => createRack.mutate()}
                disabled={!rackForm.name || createRack.isPending}
                className="px-4 py-2 text-sm bg-orange-600 hover:bg-orange-500 text-white rounded-lg disabled:opacity-50"
              >
                {createRack.isPending ? t('exa_saving') : t('save')}
              </button>
            </div>
          </div>
        </div>
      )}

      {allowInventoryEdit && addNodeRackId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold">{t('exa_add_node_title')}</h3>
              <button onClick={() => setAddNodeRackId(null)} className="text-slate-500 hover:text-white"><X size={18} /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-slate-500 block mb-1">{t('label_type')}</label>
                <select
                  value={nodeForm.role}
                  onChange={e => setNodeForm(p => ({ ...p, role: e.target.value }))}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
                >
                  <option value="compute_node">Compute Node</option>
                  <option value="storage_cell">Storage Cell</option>
                  <option value="ib_switch">IB Switch</option>
                  <option value="other">{t('filter_os_other')}</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-500 block mb-1">{t('exa_name_req')}</label>
                <input value={nodeForm.name} onChange={e => setNodeForm(p => ({ ...p, name: e.target.value }))} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white" />
              </div>
              <div>
                <label className="text-xs text-slate-500 block mb-1">IP</label>
                <input value={nodeForm.ip_address} onChange={e => setNodeForm(p => ({ ...p, ip_address: e.target.value }))} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white" />
              </div>
              {nodeForm.role === 'compute_node' && (
                <div className="grid grid-cols-2 gap-2">
                  <input placeholder="CPU" value={nodeForm.cpu_cores} onChange={e => setNodeForm(p => ({ ...p, cpu_cores: e.target.value }))} className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white" />
                  <input placeholder={t('exa_memory_gb')} value={nodeForm.memory_gb} onChange={e => setNodeForm(p => ({ ...p, memory_gb: e.target.value }))} className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white" />
                </div>
              )}
              {nodeForm.role === 'storage_cell' && (
                <input placeholder={t('exa_storage_tb')} value={nodeForm.storage_tb} onChange={e => setNodeForm(p => ({ ...p, storage_tb: e.target.value }))} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white" />
              )}
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button onClick={() => setAddNodeRackId(null)} className="px-4 py-2 text-sm text-slate-400">{t('cancel')}</button>
              <button onClick={() => addNode.mutate()} disabled={!nodeForm.name || addNode.isPending} className="px-4 py-2 text-sm bg-orange-600 hover:bg-orange-500 text-white rounded-lg disabled:opacity-50">
                {addNode.isPending ? t('exa_adding') : t('add')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
