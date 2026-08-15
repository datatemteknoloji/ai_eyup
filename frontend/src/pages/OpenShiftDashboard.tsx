/**
 * OpenShift Container Platform Dashboard — cluster bağlantısı, node/proje/workload envanteri.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Boxes, Server, Layers, Plus, RefreshCw, X, Check, Trash2, Cpu, MemoryStick, Info, Monitor, ChevronRight, Terminal, KeyRound,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { inventoryHeaders } from '../lib/inventoryApi'
import { useAuth } from '../auth/AuthContext'
import { useT } from '../i18n/LocaleProvider'
import type { TranslationKey } from '../i18n/messages'
import OcpVmDetailDrawer from '../components/openshift/OcpVmDetailDrawer'

type DashTab = 'overview' | 'clusters' | 'vms' | 'nodes' | 'projects' | 'workloads' | 'risks' | 'storage' | 'resources'

const VALID_TABS: DashTab[] = ['overview', 'clusters', 'vms', 'nodes', 'projects', 'workloads', 'risks', 'storage', 'resources']
const INVENTORY_TABS: DashTab[] = ['overview', 'vms', 'projects', 'workloads', 'risks', 'storage', 'resources']
const INTEGRATION_TABS: DashTab[] = ['overview', 'clusters', 'nodes']

function parseTab(raw: string | null | undefined): DashTab | null {
  if (raw && VALID_TABS.includes(raw as DashTab)) return raw as DashTab
  return null
}

/** Bağlantı / token alma alternatifleri — bastion üzerinde `oc` ile. */
function OpenShiftConnectHelp({ compact = false, align = 'right' }: { compact?: boolean; align?: 'left' | 'right' }) {
  const t = useT()
  const [open, setOpen] = useState(false)
  return (
    <div
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label={t('ocp_connect_help_aria')}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onBlur={(e) => {
          if (!e.currentTarget.parentElement?.contains(e.relatedTarget as Node)) setOpen(false)
        }}
        className={`inline-flex items-center justify-center rounded-full text-slate-400 hover:text-rose-300 hover:bg-rose-500/10 transition-colors ${
          compact ? 'w-6 h-6' : 'w-7 h-7'
        }`}
      >
        <Info size={compact ? 14 : 16} />
      </button>
      {open && (
        <div
          role="tooltip"
          className={`absolute z-50 top-full mt-2 w-[min(92vw,28rem)] rounded-xl border border-white/[0.1] bg-cyber-deep shadow-xl p-4 text-left ${
            align === 'left' ? 'left-0' : 'right-0'
          }`}
        >
          <div className="text-sm font-medium text-white mb-2">{t('ocp_how_connect')}</div>
          <div className="space-y-3 text-[11px] text-slate-300 leading-relaxed">
            <div>
              <div className="text-rose-300/90 font-medium mb-1">{t('ocp_help_api_title')}</div>
              <p className="text-slate-400 mb-1">{t('ocp_help_api_body')}</p>
              <pre className="bg-black/40 rounded-lg px-2.5 py-2 text-[10px] text-cyan-200/90 overflow-x-auto whitespace-pre-wrap">{`https://api.<cluster>:6443
# DNS yoksa:
https://<api-ip>:6443`}</pre>
            </div>
            <div>
              <div className="text-rose-300/90 font-medium mb-1">{t('ocp_help_sa_title')}</div>
              <p className="text-slate-400 mb-1">{t('ocp_help_sa_body')}</p>
              <pre className="bg-black/40 rounded-lg px-2.5 py-2 text-[10px] text-cyan-200/90 overflow-x-auto whitespace-pre-wrap">{`oc create sa ainew-viewer -n default
oc adm policy add-cluster-role-to-user cluster-reader -z ainew-viewer -n default
oc create token ainew-viewer -n default --duration=8760h`}</pre>
              <p className="text-slate-500 mt-1">{t('ocp_help_sa_hint')}</p>
            </div>
            <div>
              <div className="text-rose-300/90 font-medium mb-1">{t('ocp_help_user_title')}</div>
              <pre className="bg-black/40 rounded-lg px-2.5 py-2 text-[10px] text-cyan-200/90 overflow-x-auto">{`oc login … && oc whoami -t`}</pre>
              <p className="text-slate-500 mt-1">{t('ocp_help_user_hint')}</p>
            </div>
            <div>
              <div className="text-rose-300/90 font-medium mb-1">{t('ocp_help_cred_title')}</div>
              <p className="text-slate-400">{t('ocp_help_cred_body')}</p>
            </div>
            <p className="text-slate-500 border-t border-white/[0.06] pt-2">{t('ocp_help_ssl')}</p>
          </div>
        </div>
      )}
    </div>
  )
}

interface Cluster {
  id: number; name: string; api_url: string; status: string | null; version: string | null
  last_sync: string | null; sync_job?: { status?: string; phase?: string; percent?: number; message?: string } | null
  auth_method?: string; verify_ssl?: boolean; has_token?: boolean
}

interface OcpNode {
  id: number; cluster_id: number; name: string; role: string; status: string
  cpu_cores?: number; memory_gb?: number; kubelet_version?: string
  cpu_usage_pct?: number | null; memory_usage_pct?: number | null
  cpu_requested?: number; memory_requested_gb?: number
  cpu_allocatable?: number; memory_allocatable_gb?: number
  pod_count?: number
  internal_ip?: string; external_ip?: string; ip_address?: string; hostname?: string
}

interface OcpProject {
  id: number; cluster_id: number; name: string; status: string
  pod_count: number; deployment_count: number; route_count: number
  display_name?: string; is_system?: boolean
}

interface OcpWorkload {
  id: number; cluster_id: number; project: string; kind: string; name: string
  status: string; node_name?: string; restart_count: number; ready?: string; host?: string
  is_risk?: boolean; risk_severity?: string | null; reason?: string
}

interface HealthBoard {
  overall: string
  totals: {
    clusters: number; nodes: number; nodes_not_ready: number; projects: number
    pods: number; risk_pods: number; deployments: number; routes: number
  }
  clusters: Array<{
    id: number; name: string; health: string; status: string; version?: string
    node_count: number; nodes_ready: number; nodes_not_ready: string[]
    project_count: number; pod_count: number; risk_pod_count: number
    avg_cpu_request_pct?: number | null; avg_memory_request_pct?: number | null
    top_risks: Array<{ name: string; project: string; status: string; restart_count: number; severity: string }>
    last_sync?: string | null
  }>
}

interface TopologyData {
  project: string
  nodes: Array<{ id: string; kind: string; name: string; status?: string; host?: string; node_name?: string; ready?: string; restart_count?: number }>
  edges: Array<{ from: string; to: string; rel: string }>
  summary: { routes: number; services: number; deployments: number; pods: number }
}

function relTime(iso: string | null | undefined, tr: (key: TranslationKey, vars?: Record<string, string | number>) => string): string {
  if (!iso) return '—'
  const ts = new Date(iso).getTime()
  if (Number.isNaN(ts)) return '—'
  const m = Math.floor((Date.now() - ts) / 60000)
  if (m < 1) return tr('ocp_rel_now')
  if (m < 60) return tr('ocp_rel_min_ago', { n: m })
  const h = Math.floor(m / 60)
  if (h < 24) return tr('ocp_rel_hour_ago', { n: h })
  return tr('ocp_rel_day_ago', { n: Math.floor(h / 24) })
}

function statusColor(status?: string) {
  const s = (status || '').toLowerCase()
  if (['ready', 'running', 'active', 'admitted', 'available', 'healthy', 'online'].includes(s)) return 'text-green-400'
  if (['pending', 'progressing', 'warning', 'syncing'].includes(s)) return 'text-amber-400'
  if (['notready', 'failed', 'error', 'crashloopbackoff', 'critical', 'imagepullbackoff', 'oomkilled'].includes(s)) return 'text-red-400'
  return 'text-slate-400'
}

function healthTone(h?: string) {
  if (h === 'critical') return 'border-red-500/40 bg-red-500/10'
  if (h === 'warning') return 'border-amber-500/40 bg-amber-500/10'
  if (h === 'healthy') return 'border-emerald-500/30 bg-emerald-500/5'
  return 'border-white/[0.06] bg-cyber-card'
}

function CapacityBar({ pct, label }: { pct?: number | null; label: string }) {
  const v = Math.min(100, Math.max(0, pct ?? 0))
  const tone = v >= 90 ? 'bg-red-500' : v >= 75 ? 'bg-amber-500' : 'bg-emerald-500'
  return (
    <div className="min-w-[7rem]">
      <div className="flex justify-between text-[10px] text-slate-500 mb-0.5">
        <span>{label}</span>
        <span>{pct == null ? '—' : `${pct}%`}</span>
      </div>
      <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
        <div className={`h-full ${tone}`} style={{ width: `${pct == null ? 0 : v}%` }} />
      </div>
    </div>
  )
}

function PodDetailDrawer({
  clusterId, namespace, pod, onClose,
}: { clusterId: number; namespace: string; pod: string; onClose: () => void }) {
  const t = useT()
  const [prev, setPrev] = useState(false)
  const { data: detail, isLoading } = useQuery({
    queryKey: ['ocp-pod-detail', clusterId, namespace, pod],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/pods/${encodeURIComponent(namespace)}/${encodeURIComponent(pod)}`)
      if (!r.ok) throw new Error((await r.json()).detail || t('ocp_pod_detail_fail'))
      return r.json()
    },
  })
  const { data: logs, isFetching: logsLoading, refetch: refetchLogs } = useQuery({
    queryKey: ['ocp-pod-logs', clusterId, namespace, pod, prev],
    queryFn: async () => {
      const params = new URLSearchParams({ tail: '400', previous: String(prev) })
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/pods/${encodeURIComponent(namespace)}/${encodeURIComponent(pod)}/logs?${params}`)
      if (!r.ok) throw new Error(t('ocp_log_fail'))
      return r.json()
    },
  })

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <div className="w-full max-w-2xl h-full bg-cyber-card border-l border-white/[0.08] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 px-5 py-4 border-b border-white/[0.06] bg-cyber-card">
          <div>
            <div className="text-white font-medium">{namespace} / {pod}</div>
            <div className="text-xs text-slate-500">{t('ocp_pod_detail_sub')}</div>
          </div>
          <button type="button" onClick={onClose} className="p-2 rounded-lg text-slate-400 hover:bg-white/[0.06]"><X size={18} /></button>
        </div>
        <div className="p-5 space-y-4">
          {isLoading && <div className="text-sm text-slate-400 flex items-center gap-2"><RefreshCw size={14} className="animate-spin" /> {t('loading')}</div>}
          {detail && (
            <>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-lg border border-white/[0.06] bg-cyber-deep/50 px-3 py-2">
                  <div className="text-slate-500">Phase</div>
                  <div className={`font-medium ${statusColor(detail.phase)}`}>{detail.phase}</div>
                </div>
                <div className="rounded-lg border border-white/[0.06] bg-cyber-deep/50 px-3 py-2">
                  <div className="text-slate-500">Node</div>
                  <div className="text-white truncate">{detail.node || '—'}</div>
                </div>
              </div>
              <div>
                <div className="text-xs uppercase text-slate-500 mb-2">Containers</div>
                <div className="space-y-1.5">
                  {(detail.containers || []).map((c: any) => (
                    <div key={c.name} className="rounded-lg border border-white/[0.06] px-3 py-2 text-xs">
                      <div className="flex justify-between gap-2">
                        <span className="text-white">{c.name}</span>
                        <span className={statusColor(c.reason || c.state)}>{c.reason || c.state}</span>
                      </div>
                      <div className="text-slate-500 mt-0.5 truncate">{t('ocp_restart_n', { n: c.restart_count })} · {c.image}</div>
                    </div>
                  ))}
                </div>
              </div>
              {(detail.events || []).length > 0 && (
                <div>
                  <div className="text-xs uppercase text-slate-500 mb-2">Events</div>
                  <div className="space-y-1 max-h-40 overflow-y-auto">
                    {(detail.events || []).map((e: any, i: number) => (
                      <div key={i} className="text-[11px] text-slate-400 border-b border-white/[0.04] py-1">
                        <span className={e.type === 'Warning' ? 'text-amber-400' : 'text-slate-500'}>{e.reason}</span>
                        {' — '}{e.message}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs uppercase text-slate-500">Logs</div>
              <div className="flex items-center gap-2">
                <label className="text-[11px] text-slate-400 flex items-center gap-1">
                  <input type="checkbox" checked={prev} onChange={e => setPrev(e.target.checked)} />
                  {t('ocp_previous')}
                </label>
                <button type="button" onClick={() => refetchLogs()} className="text-[11px] text-rose-300 flex items-center gap-1">
                  <RefreshCw size={11} className={logsLoading ? 'animate-spin' : ''} /> {t('refresh_action')}
                </button>
              </div>
            </div>
            {logs?.error && <div className="text-xs text-amber-400 mb-2">{logs.error}</div>}
            <pre className="bg-black/40 rounded-lg p-3 text-[10px] text-cyan-100/90 overflow-auto max-h-80 whitespace-pre-wrap font-mono">
              {logsLoading ? '…' : (logs?.logs || t('ocp_empty_paren'))}
            </pre>
          </div>
        </div>
      </div>
    </div>
  )
}

function TopologyDrawer({
  clusterId, project, onClose,
}: { clusterId: number; project: string; onClose: () => void }) {
  const t = useT()
  const { data, isLoading, error } = useQuery<TopologyData>({
    queryKey: ['openshift-topology', clusterId, project],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/topology?project=${encodeURIComponent(project)}`)
      if (!r.ok) throw new Error((await r.json()).detail || t('ocp_topo_fail'))
      return r.json()
    },
  })

  const kindOrder = ['route', 'service', 'deployment', 'pod', 'node']
  const grouped = kindOrder.map(k => ({
    kind: k,
    items: (data?.nodes || []).filter(n => n.kind === k),
  })).filter(g => g.items.length > 0)

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <div
        className="w-full max-w-xl h-full bg-cyber-card border-l border-white/[0.08] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 px-5 py-4 border-b border-white/[0.06] bg-cyber-card">
          <div>
            <div className="text-white font-medium">Topology · {project}</div>
            <div className="text-xs text-slate-500">
              {data?.summary
                ? `${data.summary.routes} route · ${data.summary.services} svc · ${data.summary.deployments} deploy · ${data.summary.pods} pod`
                : 'Route → Service → Deployment → Pod → Node'}
            </div>
          </div>
          <button type="button" onClick={onClose} className="p-2 rounded-lg text-slate-400 hover:bg-white/[0.06]"><X size={18} /></button>
        </div>
        <div className="p-5 space-y-5">
          {isLoading && <div className="text-sm text-slate-400 flex items-center gap-2"><RefreshCw size={14} className="animate-spin" /> {t('ocp_topo_loading')}</div>}
          {error && <div className="text-sm text-red-400">{error instanceof Error ? error.message : t('error_generic')}</div>}
          {grouped.map(g => (
            <div key={g.kind}>
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">{g.kind} ({g.items.length})</div>
              <div className="space-y-1.5">
                {g.items.map(n => (
                  <div key={n.id} className="rounded-lg border border-white/[0.06] bg-cyber-deep/60 px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm text-white truncate">{n.name}</span>
                      <span className={`text-xs ${statusColor(n.status)}`}>{n.status || '—'}</span>
                    </div>
                    <div className="text-[11px] text-slate-500 mt-0.5 truncate">
                      {n.host || n.node_name || n.ready || ''}
                      {n.restart_count != null && n.restart_count > 0 ? ` · ${t('ocp_restart_n', { n: n.restart_count })}` : ''}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {data && (data.edges || []).length > 0 && (
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">{t('ocp_relations', { n: (data.edges || []).length })}</div>
              <div className="max-h-48 overflow-y-auto space-y-1 text-[11px] font-mono text-slate-400">
                {(data.edges || []).slice(0, 80).map((e, i) => (
                  <div key={i}>{e.from} —{e.rel}→ {e.to}</div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function openVmConsole(clusterId: number, namespace: string, name: string) {
  const title = encodeURIComponent(`${namespace}/${name}`)
  const url =
    `/openshift/vms/${clusterId}/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/console?title=${title}`
  window.open(url, `ocp-console-${namespace}-${name}`, 'width=1100,height=720')
}

function ClusterOverviewPanel({ overview }: { overview: any }) {
  const t = useT()
  if (!overview) return null
  const cap = overview.capacity || {}
  return (
    <div className="mt-4 pt-4 border-t border-white/[0.06] space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs text-slate-400">
          {t('ocp_live_config', { v: overview.version || '—' })}
          {overview.migration_ready ? (
            <span className="ml-2 text-emerald-400">· {t('ocp_mig_ready')}</span>
          ) : null}
        </div>
        {overview.migration_missing?.length > 0 && (
          <div className="text-[11px] text-amber-400">{t('ocp_missing', { list: overview.migration_missing.join(', ') })}</div>
        )}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
          <div className="text-slate-500">CPU</div>
          <div className="text-white">{cap.cpu_used_cores ?? '—'} / {cap.cpu_cores ?? '—'} core</div>
        </div>
        <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
          <div className="text-slate-500">Memory</div>
          <div className="text-white">{cap.memory_used_gb ?? '—'} / {cap.memory_gb ?? '—'} GB</div>
        </div>
        <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
          <div className="text-slate-500">Nodes / Pods</div>
          <div className="text-white">{cap.nodes_ready ?? '—'}/{cap.nodes_total ?? '—'} · {cap.pods_running ?? '—'} run</div>
        </div>
        <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
          <div className="text-slate-500">KubeVirt VM</div>
          <div className="text-white">{overview.kubevirt_vms ?? '—'}</div>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {(overview.operators || []).map((o: any) => (
          <span key={o.group} className={`text-[10px] px-2 py-0.5 rounded-full border ${
            o.installed ? 'border-emerald-500/30 text-emerald-300' : 'border-white/[0.08] text-slate-500'
          }`}>
            {(o.label || o.group || '').split('(')[0].trim()}{o.installed ? '' : ' ✕'}
          </span>
        ))}
      </div>
      {(overview.storage_classes || []).length > 0 && (
        <div>
          <div className="text-[10px] uppercase text-slate-500 mb-1">StorageClass</div>
          <div className="flex flex-wrap gap-1.5">
            {(overview.storage_classes || []).map((sc: any) => (
              <span key={sc.name} className="text-[10px] px-2 py-0.5 rounded border border-white/[0.08] text-slate-300">
                {sc.name}{sc.default ? t('ocp_sc_default_paren') : ''}
              </span>
            ))}
          </div>
        </div>
      )}
      {overview.namespaces && (
        <div className="text-[11px] text-slate-500">
          {t('ocp_ns_total', { n: overview.namespaces.total ?? '—'})}
          {overview.namespaces.user?.length != null ? ` · ${t('ocp_ns_user', { n: overview.namespaces.user.length })}` : ''}
        </div>
      )}
    </div>
  )
}

function EditClusterModal({
  cluster,
  onClose,
  onSave,
  saving,
}: {
  cluster: Cluster
  onClose: () => void
  onSave: (data: Record<string, unknown>) => void
  saving?: boolean
}) {
  const t = useT()
  const [form, setForm] = useState({
    name: cluster.name,
    api_url: cluster.api_url,
    token: '',
    username: '',
    password: '',
    verify_ssl: Boolean(cluster.verify_ssl),
  })
  const [authMethod, setAuthMethod] = useState<'token' | 'credentials'>(
    cluster.auth_method === 'credentials' ? 'credentials' : 'token',
  )

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const data: Record<string, unknown> = {
      name: form.name.trim(),
      api_url: form.api_url.trim(),
      verify_ssl: form.verify_ssl,
    }
    if (authMethod === 'token') {
      if (form.token.trim()) data.token = form.token.trim()
    } else if (form.username && form.password) {
      data.username = form.username
      data.password = form.password
    }
    onSave(data)
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-cyber-card rounded-2xl border border-white/[0.06] w-full max-w-md shadow-2xl">
        <div className="px-6 py-4 border-b border-white/[0.06] flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">{t('ocp_edit_token')}</h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">{t('name')}</label>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white" />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">{t('ocp_api_url')}</label>
            <input value={form.api_url} onChange={(e) => setForm({ ...form, api_url: e.target.value })}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white font-mono" />
          </div>
          <div className="grid grid-cols-2 gap-2 p-1 bg-cyber-deep border border-white/[0.06] rounded-lg">
            <button type="button" onClick={() => setAuthMethod('token')}
              className={`py-1.5 rounded-md text-sm ${authMethod === 'token' ? 'bg-rose-600 text-white' : 'text-slate-400'}`}>
              Bearer Token
            </button>
            <button type="button" onClick={() => setAuthMethod('credentials')}
              className={`py-1.5 rounded-md text-sm ${authMethod === 'credentials' ? 'bg-rose-600 text-white' : 'text-slate-400'}`}>
              {t('ocp_user_pass_short')}
            </button>
          </div>
          {authMethod === 'token' ? (
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">{t('ocp_new_token')} <span className="text-slate-600">{t('ocp_token_keep')}</span></label>
              <textarea rows={3} value={form.token} onChange={(e) => setForm({ ...form, token: e.target.value })}
                className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white font-mono" />
            </div>
          ) : (
            <>
              <input placeholder={t('ocp_username')} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })}
                className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white" />
              <input type="password" placeholder={t('ocp_password_ph')} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })}
                className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white" />
            </>
          )}
          <label className="flex items-center gap-2 text-xs text-slate-400">
            <input type="checkbox" checked={form.verify_ssl} onChange={(e) => setForm({ ...form, verify_ssl: e.target.checked })} />
            {t('ocp_ssl_verify')}
          </label>
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 px-4 py-2.5 bg-white/[0.07] text-white rounded-lg text-sm">{t('cancel')}</button>
            <button type="submit" disabled={saving}
              className="flex-1 px-4 py-2.5 bg-gradient-to-r from-rose-600 to-red-700 text-white rounded-lg text-sm font-medium disabled:opacity-50">
              {t('save')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function AddClusterModal({ onClose, onCreate }: { onClose: () => void; onCreate: (data: any) => void }) {
  const t = useT()
  const [form, setForm] = useState({ name: '', api_url: '', token: '', username: '', password: '', verify_ssl: false })
  const [authMethod, setAuthMethod] = useState<'token' | 'credentials'>('token')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const buildPayload = () => ({
    name: form.name,
    api_url: form.api_url,
    verify_ssl: form.verify_ssl,
    ...(authMethod === 'token'
      ? { token: form.token }
      : { username: form.username, password: form.password }),
  })

  const canTest = Boolean(form.api_url) && (authMethod === 'token' ? Boolean(form.token) : Boolean(form.username) && Boolean(form.password))

  const testConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const r = await fetch(`${API_BASE_URL}/openshift/test-connection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildPayload()),
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
    onCreate(buildPayload())
    onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-cyber-card rounded-2xl border border-white/[0.06] w-full max-w-md shadow-2xl">
        <div className="px-6 py-4 border-b border-white/[0.06] flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <h2 className="text-lg font-semibold text-white">{t('ocp_add_cluster_title')}</h2>
            <OpenShiftConnectHelp compact />
          </div>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">{t('ocp_name_req')}</label>
            <input type="text" required value={form.name} onChange={e => { setForm({ ...form, name: e.target.value }); setTestResult(null) }}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-500/50" placeholder="Production OCP" />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">{t('ocp_auth_method')}</label>
            <div className="grid grid-cols-2 gap-2 p-1 bg-cyber-deep border border-white/[0.06] rounded-lg">
              <button type="button" onClick={() => { setAuthMethod('token'); setTestResult(null) }}
                className={`py-1.5 rounded-md text-sm font-medium transition-colors ${authMethod === 'token' ? 'bg-rose-600 text-white' : 'text-slate-400 hover:text-white'}`}>
                Bearer Token
              </button>
              <button type="button" onClick={() => { setAuthMethod('credentials'); setTestResult(null) }}
                className={`py-1.5 rounded-md text-sm font-medium transition-colors ${authMethod === 'credentials' ? 'bg-rose-600 text-white' : 'text-slate-400 hover:text-white'}`}>
                {t('ocp_user_pass')}
              </button>
            </div>
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">{t('ocp_api_url_req')}</label>
            <input type="text" required value={form.api_url} onChange={e => { setForm({ ...form, api_url: e.target.value }); setTestResult(null) }}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-500/50" placeholder="https://api.cluster.example.com:6443 veya https://IP:6443" />
            <p className="text-[11px] text-slate-500 mt-1">{t('ocp_api_hint')}</p>
          </div>
          {authMethod === 'token' ? (
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">{t('ocp_bearer_req')}</label>
              <textarea required rows={3} value={form.token} onChange={e => { setForm({ ...form, token: e.target.value }); setTestResult(null) }}
                className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-500/50 font-mono" placeholder="oc create token … veya oc whoami -t" />
            </div>
          ) : (
            <>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">{t('ocp_username_req')}</label>
                <input type="text" required value={form.username} onChange={e => { setForm({ ...form, username: e.target.value }); setTestResult(null) }}
                  className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-500/50" placeholder="kubeadmin" />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">{t('ocp_password')}</label>
                <input type="password" required value={form.password} onChange={e => { setForm({ ...form, password: e.target.value }); setTestResult(null) }}
                  className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-500/50" />
              </div>
              <p className="text-[11px] text-slate-500 leading-relaxed">
                {t('ocp_oauth_hint')}
              </p>
            </>
          )}

          <button type="button" onClick={testConnection} disabled={testing || !canTest}
            className="w-full py-2.5 bg-rose-600/20 text-rose-400 border border-rose-500/30 rounded-lg hover:bg-rose-600/30 disabled:opacity-50 text-sm font-medium flex items-center justify-center gap-2">
            {testing ? <><RefreshCw className="w-4 h-4 animate-spin" /> {t('ocp_testing')}</> : t('ocp_test_conn')}
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
              className="flex-1 px-4 py-2.5 bg-gradient-to-r from-rose-600 to-red-700 text-white rounded-lg hover:from-rose-500 hover:to-red-600 disabled:opacity-50 text-sm font-medium">
              {t('add')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function OpenShiftDashboard({
  allowInventoryEdit = false,
  initialTab = 'overview',
}: {
  allowInventoryEdit?: boolean
  initialTab?: DashTab
}) {
  const t = useT()
  const { user } = useAuth()
  const isAdmin = Boolean(user?.is_admin || user?.role === 'admin')
  /** Entegrasyonlar sayfası: bağlantı + cluster + node/kapasite. Envanter: iş yükü/VM/risk. */
  const isIntegration = allowInventoryEdit
  /** Küme ekle/sil/token — yalnızca admin (API de require_role admin). */
  const canManageClusters = allowInventoryEdit && isAdmin
  const allowedTabs = isIntegration ? INTEGRATION_TABS : INVENTORY_TABS

  const [searchParams, setSearchParams] = useSearchParams()
  const tabFromUrl = parseTab(searchParams.get('tab'))
  const resolvedInitial = (() => {
    const cand = tabFromUrl || initialTab
    if (allowedTabs.includes(cand)) return cand
    return 'overview'
  })()
  const [tab, setTab] = useState<DashTab>(resolvedInitial)
  const [showAddModal, setShowAddModal] = useState(false)
  const [editCluster, setEditCluster] = useState<Cluster | null>(null)
  const [q, setQ] = useState('')
  const [kindFilter, setKindFilter] = useState('pod')
  const [page, setPage] = useState(1)
  const [topo, setTopo] = useState<{ clusterId: number; project: string } | null>(null)
  const [podView, setPodView] = useState<{ clusterId: number; namespace: string; pod: string } | null>(null)
  const [vmView, setVmView] = useState<{ clusterId: number; namespace: string; name: string } | null>(null)
  const [expandedClusterId, setExpandedClusterId] = useState<number | null>(null)
  const [resKind, setResKind] = useState('deployments')
  const [resNs, setResNs] = useState('')
  const [yamlText, setYamlText] = useState<string | null>(null)
  const pageSize = 40
  const qc = useQueryClient()

  useEffect(() => {
    const cand = tabFromUrl || initialTab
    const next = allowedTabs.includes(cand) ? cand : 'overview'
    setTab(next)
  }, [initialTab, tabFromUrl, isIntegration])

  const { data: clustersData, isLoading: clustersLoading } = useQuery<Cluster[]>({
    queryKey: ['openshift-clusters'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters`)
      if (!r.ok) return []
      const body = await r.json()
      return Array.isArray(body?.clusters) ? body.clusters : []
    },
    refetchInterval: (query) => {
      const list = (query.state.data as Cluster[] | undefined) || []
      return list.some(c => c.sync_job?.status === 'running') ? 4000 : 60_000
    },
  })
  const clusters = clustersData ?? []

  const primaryClusterId = clusters[0]?.id
  const detailClusterId = expandedClusterId ?? primaryClusterId

  const { data: health } = useQuery<HealthBoard>({
    queryKey: ['openshift-health-board'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/health-board`)
      if (!r.ok) throw new Error('health board')
      return r.json()
    },
    refetchInterval: 30_000,
  })

  const { data: nodesData } = useQuery<OcpNode[]>({
    queryKey: ['openshift-nodes'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/nodes`)
      if (!r.ok) return []
      const body = await r.json()
      return Array.isArray(body?.nodes) ? body.nodes : []
    },
    refetchInterval: 60_000,
    enabled: isIntegration,
  })
  const nodes = nodesData ?? []

  const { data: projectsData } = useQuery<{ projects: OcpProject[]; total: number }>({
    queryKey: ['openshift-projects', q, page, tab],
    queryFn: async () => {
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
      if (q.trim()) params.set('q', q.trim())
      const r = await fetch(`${API_BASE_URL}/openshift/projects?${params}`)
      if (!r.ok) return { projects: [], total: 0 }
      return r.json()
    },
    enabled: !isIntegration && (tab === 'projects' || tab === 'overview'),
    refetchInterval: 60_000,
  })

  const { data: workloadsData } = useQuery<{ workloads: OcpWorkload[]; total: number }>({
    queryKey: ['openshift-workloads', q, kindFilter, page, tab],
    queryFn: async () => {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
        kind: kindFilter,
      })
      if (q.trim()) params.set('q', q.trim())
      const r = await fetch(`${API_BASE_URL}/openshift/workloads?${params}`)
      if (!r.ok) return { workloads: [], total: 0 }
      return r.json()
    },
    enabled: !isIntegration && tab === 'workloads',
    refetchInterval: 60_000,
  })

  const { data: risksData } = useQuery<{ risks: OcpWorkload[]; total: number }>({
    queryKey: ['openshift-risks'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/risks?limit=200`)
      if (!r.ok) return { risks: [], total: 0 }
      return r.json()
    },
    refetchInterval: 30_000,
    enabled: !isIntegration,
  })

  const { data: liveOverview } = useQuery({
    queryKey: ['openshift-overview', primaryClusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${primaryClusterId}/overview`)
      if (!r.ok) throw new Error('overview')
      return r.json()
    },
    enabled: !!primaryClusterId && (tab === 'overview' || tab === 'clusters' || isIntegration),
    refetchInterval: 60_000,
  })

  const { data: clusterDetailOverview, isFetching: clusterDetailLoading } = useQuery({
    queryKey: ['openshift-overview', detailClusterId, 'detail'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${detailClusterId}/overview`)
      if (!r.ok) throw new Error('overview')
      return r.json()
    },
    enabled: !!detailClusterId && (tab === 'clusters' || (isIntegration && tab === 'overview')),
    refetchInterval: 60_000,
  })

  const { data: opHealth } = useQuery({
    queryKey: ['openshift-op-health', primaryClusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${primaryClusterId}/operators-health`)
      if (!r.ok) throw new Error('op health')
      return r.json()
    },
    enabled: !!primaryClusterId && !isIntegration && tab === 'overview',
    refetchInterval: 60_000,
  })

  const { data: storage } = useQuery({
    queryKey: ['openshift-storage', primaryClusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${primaryClusterId}/storage`)
      if (!r.ok) throw new Error('storage')
      return r.json()
    },
    enabled: !!primaryClusterId && !isIntegration && tab === 'storage',
  })

  const { data: kubevirtVms, isFetching: vmsLoading } = useQuery({
    queryKey: ['openshift-kubevirt-vms', primaryClusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${primaryClusterId}/kubevirt/vms`)
      if (!r.ok) throw new Error((await r.json()).detail || t('ocp_vm_list_fail'))
      return r.json()
    },
    enabled: !!primaryClusterId && !isIntegration && tab === 'vms',
    refetchInterval: 30_000,
  })

  const { data: resKinds } = useQuery({
    queryKey: ['openshift-resource-kinds'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/resource-kinds`)
      if (!r.ok) return { kinds: [] }
      return r.json()
    },
    enabled: !isIntegration && tab === 'resources',
  })

  const { data: resources, isFetching: resLoading } = useQuery({
    queryKey: ['openshift-resources', primaryClusterId, resKind, resNs],
    queryFn: async () => {
      const params = new URLSearchParams({ kind: resKind })
      if (resNs.trim()) params.set('namespace', resNs.trim())
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${primaryClusterId}/resources?${params}`)
      if (!r.ok) throw new Error('resources')
      return r.json()
    },
    enabled: !!primaryClusterId && !isIntegration && tab === 'resources',
  })

  const createMutation = useMutation({
    mutationFn: async (data: any) => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters`, {
        method: 'POST',
        headers: inventoryHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(data),
      })
      if (!r.ok) throw new Error((await r.json()).detail || t('ocp_add_fail'))
      return r.json()
    },
    onSuccess: async (created) => {
      qc.invalidateQueries({ queryKey: ['openshift-clusters'] })
      await fetch(`${API_BASE_URL}/openshift/clusters/${created.id}/sync?background=true`, { method: 'POST', headers: inventoryHeaders() })
      qc.invalidateQueries({ queryKey: ['openshift-clusters'] })
      qc.invalidateQueries({ queryKey: ['openshift-health-board'] })
    },
    onError: (e) => alert(e instanceof Error ? e.message : t('ocp_add_fail')),
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${id}`, { method: 'DELETE', headers: inventoryHeaders() })
      if (!r.ok) {
        const data = await r.json().catch(() => ({}))
        throw new Error(data.detail || t('ocp_delete_fail'))
      }
    },
    onSuccess: () => {
      ;['openshift-clusters', 'openshift-nodes', 'openshift-projects', 'openshift-workloads', 'openshift-health-board', 'openshift-risks'].forEach(k =>
        qc.invalidateQueries({ queryKey: [k] }),
      )
    },
    onError: (e) => alert(e instanceof Error ? e.message : t('ocp_delete_fail')),
  })

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: Record<string, unknown> }) => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${id}`, {
        method: 'PUT',
        headers: inventoryHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(data),
      })
      const body = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(body.detail || t('ocp_update_fail'))
      return body
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['openshift-clusters'] })
      setEditCluster(null)
    },
    onError: (e) => alert(e instanceof Error ? e.message : t('ocp_update_fail')),
  })

  const syncMutation = useMutation({
    mutationFn: async (id: number) => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${id}/sync?background=true`, { method: 'POST', headers: inventoryHeaders() })
      if (!r.ok) throw new Error(t('ocp_sync_fail'))
      return r.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['openshift-clusters'] })
      setTimeout(() => {
        ;['openshift-nodes', 'openshift-projects', 'openshift-workloads', 'openshift-health-board', 'openshift-risks'].forEach(k =>
          qc.invalidateQueries({ queryKey: [k] }),
        )
      }, 5000)
    },
    onError: (e) => alert(e instanceof Error ? e.message : t('ocp_sync_fail')),
  })

  const switchTab = (next: DashTab) => {
    setTab(next)
    setPage(1)
    if (next === 'overview') setSearchParams({}, { replace: true })
    else setSearchParams({ tab: next }, { replace: true })
  }

  const nodeRoleCounts = useMemo(() => {
    let master = 0
    let worker = 0
    let other = 0
    for (const n of nodes) {
      const role = (n.role || '').toLowerCase()
      if (role.includes('master') || role.includes('control')) master += 1
      else if (role.includes('worker')) worker += 1
      else other += 1
    }
    return { master, worker, other }
  }, [nodes])

  if (clustersLoading) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center">
        <div className="w-12 h-12 border-4 border-rose-500/30 border-t-rose-500 rounded-full animate-spin" />
      </div>
    )
  }

  const totals = health?.totals
  const projects = projectsData?.projects || []
  const workloads = workloadsData?.workloads || []
  const risks = risksData?.risks || []
  const projectTotal = projectsData?.total || 0
  const workloadTotal = workloadsData?.total || 0

  const nsTotal = liveOverview?.namespaces?.total
  const userProjects = liveOverview?.namespaces?.user?.length

  const tabLabels: { id: DashTab; label: string }[] = isIntegration
    ? [
        { id: 'overview', label: t('ocp_tab_summary') },
        { id: 'clusters', label: t('ocp_tab_clusters') },
        { id: 'nodes', label: t('ocp_tab_nodes') },
      ]
    : [
        { id: 'overview', label: t('ocp_tab_summary') },
        { id: 'vms', label: t('nav_virtual_machines') },
        { id: 'projects', label: t('ocp_projects') },
        { id: 'workloads', label: t('ocp_tab_workloads') },
        { id: 'risks', label: risks.length ? t('ocp_tab_risks_n', { n: risks.length }) : t('ocp_tab_risks') },
        { id: 'storage', label: t('ocp_nav_storage') },
        { id: 'resources', label: t('ocp_tab_resources') },
      ]

  return (
    <div className="space-y-5">
      {showAddModal && canManageClusters && (
        <AddClusterModal onClose={() => setShowAddModal(false)} onCreate={data => createMutation.mutate(data)} />
      )}
      {editCluster && canManageClusters && (
        <EditClusterModal
          cluster={editCluster}
          onClose={() => setEditCluster(null)}
          onSave={(data) => updateMutation.mutate({ id: editCluster.id, data })}
          saving={updateMutation.isPending}
        />
      )}
      {topo && <TopologyDrawer clusterId={topo.clusterId} project={topo.project} onClose={() => setTopo(null)} />}
      {podView && (
        <PodDetailDrawer
          clusterId={podView.clusterId}
          namespace={podView.namespace}
          pod={podView.pod}
          onClose={() => setPodView(null)}
        />
      )}
      {vmView && (
        <OcpVmDetailDrawer
          clusterId={vmView.clusterId}
          namespace={vmView.namespace}
          name={vmView.name}
          onClose={() => setVmView(null)}
          onYaml={(y) => setYamlText(y)}
        />
      )}
      {yamlText != null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setYamlText(null)}>
          <div className="w-full max-w-3xl max-h-[85vh] bg-cyber-card border border-white/[0.08] rounded-xl overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
              <span className="text-sm text-white">Resource YAML</span>
              <button type="button" onClick={() => setYamlText(null)} className="text-slate-400"><X size={16} /></button>
            </div>
            <pre className="p-4 text-[11px] text-cyan-100/90 overflow-auto max-h-[75vh] font-mono whitespace-pre-wrap">{yamlText}</pre>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white flex items-center gap-2">
            <Boxes className="text-rose-400" size={22} />
            {isIntegration ? t('ocp_int_title') : t('ocp_inv_title')}
            <OpenShiftConnectHelp align="left" />
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            {isIntegration
              ? t('ocp_int_sub')
              : t('ocp_inv_sub')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isIntegration ? (
            <>
              <Link
                to="/openshift"
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm text-slate-300 border border-white/[0.08] hover:bg-white/[0.04]"
              >
                {t('ocp_go_inventory')} <ChevronRight size={14} />
              </Link>
              {canManageClusters ? (
                <button onClick={() => setShowAddModal(true)}
                  className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-rose-600 to-red-700 text-white rounded-lg text-sm font-medium hover:from-rose-500 hover:to-red-600">
                  <Plus size={16} /> {t('ocp_add_cluster')}
                </button>
              ) : (
                <span className="text-[11px] text-slate-500">{t('ocp_admin_only')}</span>
              )}
            </>
          ) : (
            <Link
              to="/integrations/openshift"
              className="text-xs text-slate-500 hover:text-rose-300"
            >
              {t('ocp_conn_mgmt')}
            </Link>
          )}
        </div>
      </div>

      {isIntegration ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
          {[
            ['Cluster', clusters.length],
            ['Node', nodes.length || totals?.nodes || 0],
            ['Master', nodeRoleCounts.master],
            ['Worker', nodeRoleCounts.worker],
            ['Namespace', nsTotal ?? totals?.projects ?? '—'],
            [t('ocp_kpi_user_proj'), userProjects ?? '—'],
          ].map(([label, val]) => (
            <div key={String(label)} className="rounded-xl border border-white/[0.06] bg-cyber-card p-3">
              <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
              <div className="text-xl font-bold text-white">{val as number | string}</div>
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
          {[
            [t('ocp_project'), totals?.projects ?? 0],
            ['Pod', totals?.pods ?? 0],
            ['Risk', totals?.risk_pods ?? risks.length, true],
            ['Deploy', totals?.deployments ?? 0],
            ['Route', totals?.routes ?? 0],
            ['VM', liveOverview?.kubevirt_vms ?? '—'],
          ].map(([label, val, alert]) => (
            <div key={String(label)} className={`rounded-xl border p-3 ${alert && Number(val) > 0 ? 'border-red-500/30 bg-red-500/5' : 'border-white/[0.06] bg-cyber-card'}`}>
              <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
              <div className={`text-xl font-bold ${alert && Number(val) > 0 ? 'text-red-400' : 'text-white'}`}>{val as number | string}</div>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-1 border-b border-white/[0.06] overflow-x-auto">
        {tabLabels.map(({ id, label }) => (
          <button key={id} onClick={() => switchTab(id)}
            className={`px-3 py-2 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
              tab === id ? 'border-rose-500 text-white' : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'overview' && isIntegration && (
        <div className="space-y-4">
          {clusters.length === 0 && (
            <div className="text-center py-12 text-slate-500 text-sm">
              {t('ocp_no_cluster_add')}
            </div>
          )}
          {clusters.map(c => {
            const syncing = c.sync_job?.status === 'running'
            const hb = health?.clusters?.find(h => h.id === c.id)
            return (
              <div key={c.id} className={`rounded-xl border p-4 ${healthTone(hb?.health)}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-white font-medium">{c.name}</span>
                      <span className={`text-xs uppercase ${statusColor(c.status || hb?.health || '')}`}>{c.status || hb?.health || '—'}</span>
                      <span className="text-xs text-slate-500">{c.version || liveOverview?.version || ''}</span>
                    </div>
                    <div className="text-xs text-slate-500 mt-1 truncate">{c.api_url}</div>
                    <div className="text-xs text-slate-500 mt-1">
                      {syncing ? (
                        <span className="text-cyan-400">{c.sync_job?.message || t('ocp_syncing')}</span>
                      ) : (
                        <>{t('ocp_last_sync', { time: relTime(c.last_sync, t) })}</>
                      )}
                      {hb && (
                        <> · {t('ocp_nodes_projects', { ready: hb.nodes_ready, total: hb.node_count, n: hb.project_count })}</>
                      )}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => { setExpandedClusterId(c.id); switchTab('clusters') }}
                      className="text-xs px-2.5 py-1.5 rounded-lg border border-white/[0.08] text-slate-300 hover:text-white"
                    >
                      {t('ocp_cluster_detail')}
                    </button>
                    <button
                      type="button"
                      onClick={() => syncMutation.mutate(c.id)}
                      disabled={syncing}
                      className="p-2 rounded-lg bg-white/[0.05] text-slate-300 hover:bg-white/[0.1] disabled:opacity-50"
                    >
                      <RefreshCw size={15} className={syncing ? 'animate-spin' : ''} />
                    </button>
                  </div>
                </div>
                {c.id === primaryClusterId && liveOverview && (
                  <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                    <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
                      <div className="text-slate-500">CPU</div>
                      <div className="text-white">{liveOverview.capacity?.cpu_used_cores ?? '—'} / {liveOverview.capacity?.cpu_cores ?? '—'} core</div>
                    </div>
                    <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
                      <div className="text-slate-500">Memory</div>
                      <div className="text-white">{liveOverview.capacity?.memory_used_gb ?? '—'} / {liveOverview.capacity?.memory_gb ?? '—'} GB</div>
                    </div>
                    <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
                      <div className="text-slate-500">Master / Worker</div>
                      <div className="text-white">{nodeRoleCounts.master} / {nodeRoleCounts.worker}</div>
                    </div>
                    <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
                      <div className="text-slate-500">KubeVirt VM</div>
                      <div className="text-white">{liveOverview.kubevirt_vms ?? '—'}</div>
                    </div>
                  </div>
                )}
                {c.id === primaryClusterId && liveOverview?.operators && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(liveOverview.operators || []).filter((o: any) => o.installed).map((o: any) => (
                      <span key={o.group} className="text-[10px] px-2 py-0.5 rounded-full border border-emerald-500/30 text-emerald-300">
                        {(o.label || o.group || '').split('(')[0].trim()}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
          {(totals?.nodes_not_ready || 0) > 0 && (
            <div className="text-xs text-red-300">{t('ocp_notready_n', { n: totals?.nodes_not_ready ?? 0 })}</div>
          )}
        </div>
      )}

      {tab === 'overview' && !isIntegration && (
        <div className="space-y-4">
          {liveOverview && (
            <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm text-white font-medium">{t('ocp_live_summary', { v: liveOverview.version || '—' })}</div>
                <div className="text-xs text-slate-500">
                  {liveOverview.capacity?.metrics_available ? t('ocp_metrics_on') : t('ocp_metrics_off')}
                </div>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
                  <div className="text-slate-500">CPU</div>
                  <div className="text-white">{liveOverview.capacity?.cpu_used_cores ?? '—'} / {liveOverview.capacity?.cpu_cores} core</div>
                </div>
                <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
                  <div className="text-slate-500">Memory</div>
                  <div className="text-white">{liveOverview.capacity?.memory_used_gb ?? '—'} / {liveOverview.capacity?.memory_gb} GB</div>
                </div>
                <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
                  <div className="text-slate-500">Pods running</div>
                  <div className="text-white">{liveOverview.capacity?.pods_running} / {liveOverview.capacity?.pods_total}</div>
                </div>
                <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
                  <div className="text-slate-500">KubeVirt VM</div>
                  <div className="text-white">{liveOverview.kubevirt_vms ?? '—'}</div>
                </div>
              </div>
            </div>
          )}

          {opHealth && (
            <div className={`rounded-xl border p-4 ${healthTone(opHealth.overall)}`}>
              <div className="flex items-center justify-between gap-2 mb-2">
                <div className="text-sm text-white font-medium">ClusterOperator / MCP</div>
                <span className={`text-xs uppercase ${statusColor(opHealth.overall)}`}>{opHealth.overall}</span>
              </div>
              <div className="text-xs text-slate-400 mb-2">
                {t('ocp_version', { v: opHealth.version || '—' })}
                {opHealth.updating ? ` · ${t('ocp_updating', { msg: opHealth.update_message || '' })}` : ''}
              </div>
              {(opHealth.operators?.degraded || []).length > 0 && (
                <div className="space-y-1 mb-2">
                  {(opHealth.operators?.degraded || []).slice(0, 6).map((d: any) => (
                    <div key={d.name} className="text-xs text-red-300">{d.name}: {d.reason || d.message}</div>
                  ))}
                </div>
              )}
            </div>
          )}

          {(health?.clusters || []).length === 0 && (
            <div className="text-center py-12 text-slate-500">
              <Boxes size={32} className="mx-auto mb-3 opacity-40" />
              <p className="text-sm">{t('ocp_no_cluster_int')}</p>
            </div>
          )}
          {(health?.clusters || []).map(c => (
            <div key={c.id} className={`rounded-xl border p-4 ${healthTone(c.health)}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-white font-medium">{c.name}</span>
                    <span className={`text-xs uppercase ${statusColor(c.health)}`}>{c.health}</span>
                    <span className="text-xs text-slate-500">{c.version || ''}</span>
                  </div>
                  <div className="text-xs text-slate-500 mt-1">
                    {t('ocp_cluster_stats', { ready: c.nodes_ready, nodes: c.node_count, proj: c.project_count, pods: c.pod_count, risk: c.risk_pod_count })}
                    {' · '}{t('ocp_sync_rel', { time: relTime(c.last_sync, t) })}
                  </div>
                </div>
                <div className="flex gap-4">
                  <CapacityBar pct={c.avg_cpu_request_pct} label="CPU req" />
                  <CapacityBar pct={c.avg_memory_request_pct} label="Mem req" />
                </div>
              </div>
              {Array.isArray(c.nodes_not_ready) && c.nodes_not_ready.length > 0 && (
                <div className="mt-3 text-xs text-red-300">
                  NotReady: {c.nodes_not_ready.join(', ')}
                </div>
              )}
              {c.top_risks?.length > 0 && (
                <div className="mt-3 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-[11px] text-slate-500 uppercase">{t('ocp_top_risks')}</div>
                    <button
                      type="button"
                      onClick={() => switchTab('risks')}
                      className="text-[11px] text-rose-300 hover:underline"
                    >
                      {t('ocp_all_risks', { n: c.risk_pod_count })}
                    </button>
                  </div>
                  <div className="grid sm:grid-cols-2 gap-2">
                    {c.top_risks.slice(0, 3).map((r, i) => (
                      <button
                        key={i}
                        type="button"
                        onClick={() => setPodView({ clusterId: c.id, namespace: r.project, pod: r.name })}
                        className="rounded-lg bg-black/20 border border-white/[0.05] px-3 py-2 text-xs text-left hover:border-rose-500/30"
                      >
                        <div className="flex justify-between gap-2">
                          <span className="text-white truncate">{r.project}/{r.name}</span>
                          <span className={statusColor(r.severity)}>{r.status}</span>
                        </div>
                        <div className="text-slate-500 mt-0.5">{t('ocp_restart_n', { n: r.restart_count })} · {r.severity}</div>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {(!c.top_risks || c.top_risks.length === 0) && (c.risk_pod_count || 0) > 0 && (
                <button
                  type="button"
                  onClick={() => switchTab('risks')}
                  className="mt-3 text-xs text-rose-300 hover:underline"
                >
                  {t('ocp_risk_tab', { n: c.risk_pod_count })}
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {tab === 'clusters' && isIntegration && (
        <div className="space-y-3">
          {clusters.length === 0 && (
            <div className="text-center py-12 text-slate-500 text-sm">{t('ocp_no_cluster_short')}</div>
          )}
          {clusters.map(c => {
            const syncing = c.sync_job?.status === 'running'
            const expanded = (expandedClusterId ?? clusters[0]?.id) === c.id
            return (
              <div key={c.id} className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
                <div className="flex items-center justify-between gap-4 flex-wrap">
                  <button
                    type="button"
                    className="flex items-center gap-3 min-w-0 text-left flex-1"
                    onClick={() => setExpandedClusterId(c.id)}
                  >
                    <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-rose-600 to-red-700 flex items-center justify-center flex-shrink-0">
                      <Boxes size={18} className="text-white" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-white font-medium truncate flex items-center gap-2">
                        {c.name}
                        <span className={`text-[10px] uppercase ${statusColor(c.status || '')}`}>{c.status || '—'}</span>
                      </div>
                      <div className="text-xs text-slate-500 truncate">{c.api_url}</div>
                      <div className="text-xs text-slate-500">
                        {t('ocp_ver_unknown', { v: c.version || t('ocp_unknown_ver') })}
                        {' · '}
                        {syncing ? (
                          <span className="text-cyan-400">{c.sync_job?.message || t('ocp_syncing_long')}</span>
                        ) : (
                          <>{t('ocp_last_sync', { time: relTime(c.last_sync, t) })}</>
                        )}
                      </div>
                    </div>
                  </button>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                      type="button"
                      onClick={() => setExpandedClusterId(c.id)}
                      className={`text-xs px-2.5 py-1.5 rounded-lg border ${
                        expanded ? 'border-rose-500/40 text-rose-300' : 'border-white/[0.08] text-slate-400 hover:text-white'
                      }`}
                    >
                      {expanded ? t('ocp_detail_open') : t('detail')}
                    </button>
                    {allowInventoryEdit && (
                      <button onClick={() => syncMutation.mutate(c.id)} disabled={syncing}
                        className="p-2 rounded-lg bg-white/[0.05] text-slate-300 hover:bg-white/[0.1] disabled:opacity-50"
                        title={t('exa_sync_title')}>
                        <RefreshCw size={15} className={syncing ? 'animate-spin' : ''} />
                      </button>
                    )}
                    {canManageClusters && (
                      <>
                        <button
                          type="button"
                          onClick={() => setEditCluster(c)}
                          className="p-2 rounded-lg bg-white/[0.05] text-cyan-300 hover:bg-white/[0.1]"
                          title={t('ocp_token_title')}
                        >
                          <KeyRound size={15} />
                        </button>
                        <button onClick={() => { if (confirm(t('ocp_delete_confirm', { name: c.name }))) deleteMutation.mutate(c.id) }}
                          className="p-2 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20"
                          title={t('ocp_delete_conn')}>
                          <Trash2 size={15} />
                        </button>
                      </>
                    )}
                  </div>
                </div>
                {expanded && (
                  <>
                    {clusterDetailLoading && detailClusterId === c.id && (
                      <div className="mt-3 text-xs text-slate-400 flex items-center gap-2">
                        <RefreshCw size={12} className="animate-spin" /> {t('ocp_live_detail_loading')}
                      </div>
                    )}
                    {detailClusterId === c.id && (
                      <ClusterOverviewPanel overview={clusterDetailOverview || (c.id === primaryClusterId ? liveOverview : null)} />
                    )}
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}

      {tab === 'vms' && !isIntegration && (
        <div className="space-y-3">
          {!primaryClusterId && <div className="text-sm text-slate-500">{t('ocp_add_cluster_first')}</div>}
          {vmsLoading && (
            <div className="text-xs text-slate-400 flex items-center gap-2">
              <RefreshCw size={12} className="animate-spin" /> {t('ocp_vms_loading')}
            </div>
          )}
          {kubevirtVms && kubevirtVms.installed === false && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-200">
              {t('ocp_kubevirt_missing', { msg: kubevirtVms.message || '—'})}
            </div>
          )}
          {kubevirtVms?.installed !== false && (
            <>
              <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
                <span className="flex items-center gap-1.5">
                  <Monitor size={14} /> {kubevirtVms?.total ?? 0} VirtualMachine
                </span>
                <span>{t('ocp_live_api')}</span>
              </div>
              <div className="rounded-xl border border-white/[0.06] overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-white/[0.03] text-xs text-slate-500">
                    <tr>
                      <th className="text-left px-4 py-2">{t('name')}</th>
                      <th className="text-left px-4 py-2">{t('ocp_col_project')}</th>
                      <th className="text-left px-4 py-2">{t('col_status')}</th>
                      <th className="text-left px-4 py-2">{t('ocp_col_worker')}</th>
                      <th className="text-left px-4 py-2">{t('ocp_col_cpu_mem')}</th>
                      <th className="text-left px-4 py-2">IP</th>
                      <th className="text-left px-4 py-2"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04]">
                    {(kubevirtVms?.vms || []).map((vm: any) => (
                      <tr
                        key={`${vm.namespace}/${vm.name}`}
                        className="hover:bg-white/[0.03]"
                      >
                        <td
                          className="px-4 py-2 text-white font-medium cursor-pointer"
                          onClick={() => primaryClusterId && setVmView({
                            clusterId: primaryClusterId,
                            namespace: vm.namespace,
                            name: vm.name,
                          })}
                        >{vm.name}</td>
                        <td className="px-4 py-2 text-slate-400">{vm.namespace}</td>
                        <td className={`px-4 py-2 ${statusColor(vm.phase || vm.status)}`}>{vm.phase || vm.status}</td>
                        <td className="px-4 py-2 text-slate-400">{vm.node_name || '—'}</td>
                        <td className="px-4 py-2 text-slate-500">{vm.cpu_cores ?? '—'} / {vm.memory_gb ?? '—'} GB</td>
                        <td className="px-4 py-2 text-slate-400 font-mono text-xs">{vm.ip_address || '—'}</td>
                        <td className="px-4 py-2">
                          <button
                            type="button"
                            disabled={(vm.phase || '').toLowerCase() !== 'running'}
                            title={(vm.phase || '').toLowerCase() === 'running' ? t('ocp_console_novnc') : t('ocp_vm_must_running')}
                            className="text-xs text-violet-300 disabled:opacity-30 inline-flex items-center gap-1"
                            onClick={(e) => {
                              e.stopPropagation()
                              if (primaryClusterId) openVmConsole(primaryClusterId, vm.namespace, vm.name)
                            }}
                          >
                            <Monitor size={12} /> Console
                          </button>
                        </td>
                      </tr>
                    ))}
                    {!vmsLoading && (kubevirtVms?.vms || []).length === 0 && kubevirtVms?.installed !== false && (
                      <tr>
                        <td colSpan={7} className="px-4 py-8 text-center text-slate-500 text-sm">
                          {t('ocp_no_vm')}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {tab === 'nodes' && isIntegration && (
        <div className="space-y-3">
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {nodes.map(n => {
              const notReady = (n.status || '').toLowerCase() !== 'ready'
              const tip = [
                n.internal_ip && `InternalIP: ${n.internal_ip}`,
                n.external_ip && `ExternalIP: ${n.external_ip}`,
                !n.internal_ip && !n.external_ip && t('ocp_no_ip_sync'),
              ].filter(Boolean).join('\n')
              return (
                <div
                  key={n.id}
                  title={tip}
                  className={`group relative rounded-xl border p-4 ${notReady ? 'border-red-500/40 bg-red-500/10' : 'border-white/[0.06] bg-cyber-card'}`}
                >
                  <div className="pointer-events-none absolute left-3 top-full z-20 mt-1 hidden min-w-[11rem] rounded-lg border border-white/[0.1] bg-cyber-card px-2.5 py-2 text-[11px] text-slate-200 shadow-xl group-hover:block">
                    <div className="font-medium text-slate-100">{n.name}</div>
                    <div className="text-slate-500 capitalize mt-0.5">{n.role}</div>
                    {n.internal_ip || n.ip_address ? (
                      <div className="mt-1 font-mono text-cyan-300/90">IP {n.internal_ip || n.ip_address}</div>
                    ) : (
                      <div className="mt-1 text-slate-500">{t('ocp_no_ip')}</div>
                    )}
                  </div>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-white font-medium truncate flex items-center gap-1.5">
                        <Server size={14} className="text-slate-500 shrink-0" /> {n.name}
                      </div>
                      <div className="text-xs text-slate-500 mt-0.5 capitalize">{n.role} · {t('ocp_n_pod', { n: n.pod_count ?? 0 })}</div>
                    </div>
                    <span className={`text-xs font-medium ${statusColor(n.status)}`}>{n.status}</span>
                  </div>
                  <div className="mt-3 space-y-2">
                    <CapacityBar pct={n.cpu_usage_pct} label={`CPU req (${n.cpu_requested ?? '—'} / ${n.cpu_allocatable ?? n.cpu_cores ?? '—'})`} />
                    <CapacityBar pct={n.memory_usage_pct} label={`Mem req (${n.memory_requested_gb ?? '—'} / ${n.memory_allocatable_gb ?? n.memory_gb ?? '—'} GB)`} />
                  </div>
                  <div className="mt-2 text-[10px] text-slate-500 flex gap-3">
                    <span className="flex items-center gap-1"><Cpu size={10} /> {n.cpu_cores ?? '—'} core</span>
                    <span className="flex items-center gap-1"><MemoryStick size={10} /> {n.memory_gb ?? '—'} GB</span>
                  </div>
                </div>
              )
            })}
          </div>
          {nodes.length === 0 && <div className="text-center py-10 text-slate-500 text-sm">{t('ocp_no_node')}</div>}
          <p className="text-[11px] text-slate-500">{t('ocp_cap_hint')}</p>
        </div>
      )}

      {tab === 'projects' && (
        <div className="space-y-3">
          <input
            value={q}
            onChange={e => { setQ(e.target.value); setPage(1) }}
            placeholder={t('ocp_search_project')}
            className="w-full max-w-sm bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white"
          />
          <div className="rounded-xl border border-white/[0.06] overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-white/[0.03] text-slate-500 text-xs">
                <tr>
                  <th className="text-left px-4 py-2.5">{t('ocp_col_project')}</th>
                  <th className="text-left px-4 py-2.5">{t('col_status')}</th>
                  <th className="text-left px-4 py-2.5">Pod</th>
                  <th className="text-left px-4 py-2.5">Deploy</th>
                  <th className="text-left px-4 py-2.5">Route</th>
                  <th className="text-left px-4 py-2.5"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {projects.map(p => (
                  <tr key={p.id} className="hover:bg-white/[0.02]">
                    <td className="px-4 py-2.5 text-white">
                      <div className="flex items-center gap-2"><Layers size={13} className="text-slate-500" /> {p.name}</div>
                      {p.display_name && <div className="text-[10px] text-slate-500 ml-5">{p.display_name}</div>}
                    </td>
                    <td className={`px-4 py-2.5 font-medium ${statusColor(p.status)}`}>{p.status}</td>
                    <td className="px-4 py-2.5 text-slate-400">{p.pod_count}</td>
                    <td className="px-4 py-2.5 text-slate-400">{p.deployment_count}</td>
                    <td className="px-4 py-2.5 text-slate-400">{p.route_count}</td>
                    <td className="px-4 py-2.5">
                      <button
                        type="button"
                        onClick={() => setTopo({ clusterId: p.cluster_id, project: p.name })}
                        className="text-xs text-rose-300 hover:text-rose-200"
                      >
                        Topology
                      </button>
                    </td>
                  </tr>
                ))}
                {projects.length === 0 && (
                  <tr><td colSpan={6} className="text-center py-8 text-slate-500">{t('ocp_no_project')}</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager page={page} pageSize={pageSize} total={projectTotal} onChange={setPage} />
        </div>
      )}

      {tab === 'workloads' && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <input
              value={q}
              onChange={e => { setQ(e.target.value); setPage(1) }}
              placeholder={t('ocp_search_wl')}
              className="flex-1 min-w-[12rem] max-w-sm bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white"
            />
            <select
              value={kindFilter}
              onChange={e => { setKindFilter(e.target.value); setPage(1) }}
              className="bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white"
            >
              {['pod', 'deployment', 'service', 'route'].map(k => <option key={k} value={k}>{k}</option>)}
            </select>
          </div>
          <div className="rounded-xl border border-white/[0.06] overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-white/[0.03] text-slate-500 text-xs">
                <tr>
                  <th className="text-left px-4 py-2.5">{t('ocp_kind')}</th>
                  <th className="text-left px-4 py-2.5">{t('name')}</th>
                  <th className="text-left px-4 py-2.5">{t('ocp_col_project')}</th>
                  <th className="text-left px-4 py-2.5">{t('col_status')}</th>
                  <th className="text-left px-4 py-2.5">Ready</th>
                  <th className="text-left px-4 py-2.5">Restart</th>
                  <th className="text-left px-4 py-2.5">Node / Host</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {workloads.map(w => (
                  <tr key={w.id} className={`hover:bg-white/[0.02] ${w.is_risk ? 'bg-red-500/5' : ''}`}>
                    <td className="px-4 py-2.5 text-slate-400 uppercase text-xs">{w.kind}</td>
                    <td className="px-4 py-2.5 text-white">{w.name}</td>
                    <td className="px-4 py-2.5 text-slate-400">{w.project}</td>
                    <td className={`px-4 py-2.5 font-medium ${statusColor(w.status)}`}>{w.status}</td>
                    <td className="px-4 py-2.5 text-slate-400">{w.ready || '—'}</td>
                    <td className={`px-4 py-2.5 ${(w.restart_count || 0) >= 5 ? 'text-amber-400' : 'text-slate-400'}`}>{w.restart_count}</td>
                    <td className="px-4 py-2.5 text-slate-500 text-xs">{w.node_name || w.host || '—'}</td>
                  </tr>
                ))}
                {workloads.length === 0 && (
                  <tr><td colSpan={7} className="text-center py-8 text-slate-500">{t('ocp_no_workload')}</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <Pager page={page} pageSize={pageSize} total={workloadTotal} onChange={setPage} />
        </div>
      )}

      {tab === 'risks' && (
        <div className="space-y-2">
          {risks.length === 0 && <div className="text-center py-10 text-slate-500 text-sm">{t('ocp_no_risk_pod')}</div>}
          {risks.map(w => (
            <div key={w.id} className={`rounded-xl border px-4 py-3 flex flex-wrap items-center justify-between gap-2 ${
              w.risk_severity === 'critical' ? 'border-red-500/40 bg-red-500/10' : 'border-amber-500/30 bg-amber-500/5'
            }`}>
              <div className="min-w-0">
                <div className="text-white text-sm truncate">{w.project} / {w.name}</div>
                <div className="text-xs text-slate-500">{w.node_name || '—'} · {t('ocp_restart_n', { n: w.restart_count })}</div>
              </div>
              <div className="flex items-center gap-3">
                <span className={`text-xs font-medium ${statusColor(w.status)}`}>{w.status}</span>
                <span className="text-[10px] uppercase text-slate-400">{w.risk_severity}</span>
                <button type="button" className="text-xs text-rose-300" onClick={() => setPodView({ clusterId: w.cluster_id, namespace: w.project, pod: w.name })}>
                  {t('ocp_log_detail')}
                </button>
                <button type="button" className="text-xs text-slate-400" onClick={() => setTopo({ clusterId: w.cluster_id, project: w.project })}>
                  Topology
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'storage' && (
        <div className="space-y-4">
          {!primaryClusterId && <div className="text-sm text-slate-500">{t('ocp_add_cluster_first')}</div>}
          {storage && (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {[
                  ['StorageClass', storage.summary?.storage_classes],
                  ['PV', storage.summary?.pvs],
                  ['PVC', storage.summary?.pvcs],
                  ['PVC Pending', storage.summary?.pvcs_pending],
                ].map(([l, v]) => (
                  <div key={String(l)} className={`rounded-xl border p-3 ${l === 'PVC Pending' && Number(v) > 0 ? 'border-amber-500/40 bg-amber-500/5' : 'border-white/[0.06] bg-cyber-card'}`}>
                    <div className="text-[10px] text-slate-500 uppercase">{l}</div>
                    <div className="text-xl font-bold text-white">{v}</div>
                  </div>
                ))}
              </div>
              <div className="rounded-xl border border-white/[0.06] overflow-hidden">
                <div className="px-4 py-2 text-xs text-slate-500 border-b border-white/[0.06]">StorageClass</div>
                <table className="w-full text-sm">
                  <tbody className="divide-y divide-white/[0.04]">
                    {(storage.storage_classes || []).map((sc: any) => (
                      <tr key={sc.name}>
                        <td className="px-4 py-2 text-white">{sc.name}{sc.default ? t('ocp_sc_default_paren') : ''}</td>
                        <td className="px-4 py-2 text-slate-500 text-xs">{sc.provisioner}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="rounded-xl border border-white/[0.06] overflow-hidden">
                <div className="px-4 py-2 text-xs text-slate-500 border-b border-white/[0.06]">{t('ocp_pvc_first')}</div>
                <table className="w-full text-sm">
                  <thead className="text-xs text-slate-500">
                    <tr>
                      <th className="text-left px-4 py-2">{t('name')}</th>
                      <th className="text-left px-4 py-2">NS</th>
                      <th className="text-left px-4 py-2">Phase</th>
                      <th className="text-left px-4 py-2">Cap</th>
                      <th className="text-left px-4 py-2">SC / Volume</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04]">
                    {(storage.persistent_volume_claims || []).slice(0, 40).map((p: any) => (
                      <tr key={`${p.namespace}/${p.name}`} className={p.phase === 'Pending' ? 'bg-amber-500/5' : ''}>
                        <td className="px-4 py-2 text-white">{p.name}</td>
                        <td className="px-4 py-2 text-slate-400">{p.namespace}</td>
                        <td className={`px-4 py-2 ${statusColor(p.phase)}`}>{p.phase}</td>
                        <td className="px-4 py-2 text-slate-500">{p.capacity_gb ?? '—'} GB</td>
                        <td className="px-4 py-2 text-slate-500 text-xs">{p.storage_class || '—'}{p.volume ? ` · ${p.volume}` : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="rounded-xl border border-white/[0.06] overflow-hidden">
                <div className="px-4 py-2 text-xs text-slate-500 border-b border-white/[0.06]">{t('ocp_pv_first')}</div>
                <table className="w-full text-sm">
                  <thead className="text-xs text-slate-500">
                    <tr>
                      <th className="text-left px-4 py-2">{t('name')}</th>
                      <th className="text-left px-4 py-2">Phase</th>
                      <th className="text-left px-4 py-2">Cap</th>
                      <th className="text-left px-4 py-2">Claim</th>
                      <th className="text-left px-4 py-2">SC / Reclaim</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04]">
                    {(storage.persistent_volumes || []).slice(0, 40).map((p: any) => (
                      <tr key={p.name}>
                        <td className="px-4 py-2 text-white">{p.name}</td>
                        <td className={`px-4 py-2 ${statusColor(p.phase)}`}>{p.phase}</td>
                        <td className="px-4 py-2 text-slate-500">{p.capacity_gb ?? '—'} GB</td>
                        <td className="px-4 py-2 text-slate-400 text-xs">{p.claim || '—'}</td>
                        <td className="px-4 py-2 text-slate-500 text-xs">
                          {p.storage_class || '—'}
                          {p.reclaim ? ` · ${p.reclaim}` : ''}
                        </td>
                      </tr>
                    ))}
                    {(storage.persistent_volumes || []).length === 0 && (
                      <tr>
                        <td colSpan={5} className="px-4 py-6 text-center text-slate-500 text-sm">{t('ocp_no_pv')}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {tab === 'resources' && (
        <div className="space-y-3">
          {!primaryClusterId && <div className="text-sm text-slate-500">{t('ocp_add_cluster_first')}</div>}
          <div className="flex flex-wrap gap-2">
            <select
              value={resKind}
              onChange={e => setResKind(e.target.value)}
              className="bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white"
            >
              {(resKinds?.kinds || []).map((k: any) => (
                <option key={k.id} value={k.id}>{k.label}</option>
              ))}
            </select>
            <input
              value={resNs}
              onChange={e => setResNs(e.target.value)}
              placeholder={t('ocp_ns_placeholder')}
              className="flex-1 min-w-[10rem] max-w-xs bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white"
            />
          </div>
          <p className="text-[11px] text-slate-500">
            {t('ocp_ns_hint')}
          </p>
          {resLoading && <div className="text-xs text-slate-400 flex items-center gap-2"><RefreshCw size={12} className="animate-spin" /> {t('loading')}</div>}
          {resources?.error && <div className="text-xs text-amber-400">{resources.error}</div>}
          <div className="rounded-xl border border-white/[0.06] overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-white/[0.03] text-xs text-slate-500">
                <tr>
                  <th className="text-left px-4 py-2">{t('name')}</th>
                  <th className="text-left px-4 py-2">NS</th>
                  <th className="text-left px-4 py-2">Info</th>
                  <th className="text-left px-4 py-2">Age</th>
                  <th className="text-left px-4 py-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {(resources?.items || []).slice(0, 100).map((it: any) => (
                  <tr key={`${it.namespace}/${it.name}`}>
                    <td className="px-4 py-2 text-white">{it.name}</td>
                    <td className="px-4 py-2 text-slate-400">{it.namespace || '—'}</td>
                    <td className="px-4 py-2 text-slate-400">{it.info}</td>
                    <td className="px-4 py-2 text-slate-500">{it.age}</td>
                    <td className="px-4 py-2">
                      <button
                        type="button"
                        className="text-xs text-rose-300"
                        onClick={async () => {
                          const params = new URLSearchParams({ kind: resKind, name: it.name })
                          if (it.namespace) params.set('namespace', it.namespace)
                          const r = await fetch(`${API_BASE_URL}/openshift/clusters/${primaryClusterId}/resource-yaml?${params}`)
                          const d = await r.json()
                          setYamlText(d.yaml || d.error || '—')
                        }}
                      >
                        YAML
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function Pager({ page, pageSize, total, onChange }: { page: number; pageSize: number; total: number; onChange: (p: number) => void }) {
  const t = useT()
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (total <= pageSize) return null
  return (
    <div className="flex items-center justify-between text-xs text-slate-400">
      <span>{t('ocp_pager', { total, page, pages })}</span>
      <div className="flex gap-2">
        <button type="button" disabled={page <= 1} onClick={() => onChange(page - 1)}
          className="px-3 py-1.5 rounded-lg border border-white/[0.06] disabled:opacity-40 hover:bg-white/[0.04]">{t('page_prev')}</button>
        <button type="button" disabled={page >= pages} onClick={() => onChange(page + 1)}
          className="px-3 py-1.5 rounded-lg border border-white/[0.06] disabled:opacity-40 hover:bg-white/[0.04]">{t('page_next')}</button>
      </div>
    </div>
  )
}
