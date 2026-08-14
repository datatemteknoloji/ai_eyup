/**
 * KubeVirt VM detay çekmecesi — disk/NIC/guest + snapshot/klon.
 * Liste/durum her openshift kullanıcısına açık; yazma (al/restore/sil/klon/disk) yalnızca admin.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Camera, Copy, HardDrive, Monitor, RefreshCw, Trash2, X } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useAuth } from '../../auth/AuthContext'
import { useT } from '../../i18n/LocaleProvider'

type Props = {
  clusterId: number
  namespace: string
  name: string
  onClose: () => void
  onYaml?: (yaml: string) => void
}

type Snap = { name: string; ready?: boolean; created?: string; phase?: string }
type CloneJob = { name: string; target?: string; phase?: string; ready?: boolean; created?: string }
type StorageClass = { name: string; default?: boolean }

function statusColor(status?: string) {
  const s = (status || '').toLowerCase()
  if (['ready', 'running', 'succeeded', 'available', 'true'].includes(s)) return 'text-emerald-400'
  if (['pending', 'progressing', 'inprogress', 'creating', 'snapshotinprogress'].includes(s)) return 'text-amber-400'
  if (['failed', 'error', 'notready', 'false'].includes(s)) return 'text-red-400'
  return 'text-slate-400'
}

function openVmConsole(clusterId: number, namespace: string, name: string) {
  const title = encodeURIComponent(`${namespace}/${name}`)
  const url =
    `/openshift/vms/${clusterId}/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/console?title=${title}`
  window.open(url, `ocp-console-${namespace}-${name}`, 'width=1280,height=800')
}

async function api(path: string, init?: RequestInit) {
  const r = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) {
    throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.[0]?.msg || `HTTP ${r.status}`)
  }
  return data
}

export default function OcpVmDetailDrawer({ clusterId, namespace, name, onClose, onYaml }: Props) {
  const t = useT()
  const { user } = useAuth()
  const isAdmin = Boolean(user?.is_admin || user?.role === 'admin')
  const qc = useQueryClient()
  const [yamlText, setYamlText] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [snapName, setSnapName] = useState('')
  const [cloneTarget, setCloneTarget] = useState(`${name}-clone`)
  const [diskName, setDiskName] = useState(`${name}-disk2`)
  const [diskSize, setDiskSize] = useState('20Gi')
  const [storageClass, setStorageClass] = useState('')

  const base = `/openshift/clusters/${clusterId}/kubevirt/vms/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`

  const { data: detail, isLoading, error, refetch: refetchDetail } = useQuery({
    queryKey: ['openshift-vm-detail', clusterId, namespace, name],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}${base}`)
      if (!r.ok) throw new Error((await r.json()).detail || t('ocp_vm_detail_fail'))
      return r.json()
    },
  })

  const { data: snapData, refetch: refetchSnaps } = useQuery({
    queryKey: ['openshift-vm-snapshots', clusterId, namespace, name],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}${base}/snapshots`)
      if (!r.ok) return { snapshots: [] as Snap[] }
      return r.json() as Promise<{ snapshots: Snap[] }>
    },
    refetchInterval: 15_000,
  })

  const { data: cloneData, refetch: refetchClones } = useQuery({
    queryKey: ['openshift-vm-clones', clusterId, namespace, name],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}${base}/clones`)
      if (!r.ok) return { clones: [] as CloneJob[] }
      return r.json() as Promise<{ clones: CloneJob[] }>
    },
    refetchInterval: 10_000,
  })

  const { data: storage } = useQuery({
    queryKey: ['openshift-storage', clusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/storage`)
      if (!r.ok) return { storage_classes: [] as StorageClass[] }
      return r.json()
    },
    enabled: isAdmin,
  })

  const snapshots = snapData?.snapshots || []
  const clones = cloneData?.clones || []
  const classes: StorageClass[] = storage?.storage_classes || []
  const phase = (detail?.phase || detail?.vm_power_state || '').toLowerCase()
  const canConsole = phase === 'running'
  const vmOff = !['running', 'starting', 'migrating'].includes(phase)

  const refreshAll = () => {
    refetchDetail()
    refetchSnaps()
    refetchClones()
    qc.invalidateQueries({ queryKey: ['openshift-kubevirt-vms', clusterId] })
  }

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setErr('')
    try {
      await fn()
      refreshAll()
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('ocp_action_fail'))
    } finally {
      setBusy(false)
    }
  }

  const showYaml = async () => {
    const params = new URLSearchParams({ kind: 'virtualmachines', name, namespace })
    const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/resource-yaml?${params}`)
    const d = await r.json()
    const text = d.yaml || d.error || '—'
    if (onYaml) onYaml(text)
    else setYamlText(text)
  }

  const inputCls = 'w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white'
  const btnCls = 'text-xs px-2.5 py-1.5 rounded-lg border border-white/[0.08] text-slate-200 hover:bg-white/[0.06] disabled:opacity-40 inline-flex items-center gap-1.5'

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <div className="w-full max-w-2xl h-full bg-cyber-card border-l border-white/[0.08] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 px-5 py-4 border-b border-white/[0.06] bg-cyber-card">
          <div className="min-w-0">
            <div className="text-white font-medium truncate">{namespace} / {name}</div>
            <div className="text-xs text-slate-500">{t('ocp_vm_detail_sub')}</div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={() => refreshAll()}
              className={btnCls}
              title={t('refresh_action')}
            >
              <RefreshCw size={12} className={isLoading ? 'animate-spin' : ''} />
            </button>
            <button
              type="button"
              disabled={!canConsole && !!detail}
              title={canConsole ? t('ocp_console_novnc') : t('ocp_vm_must_running')}
              className="text-xs text-violet-300 px-2 py-1 rounded border border-violet-500/30 hover:bg-violet-500/10 disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-1"
              onClick={() => openVmConsole(clusterId, namespace, name)}
            >
              <Monitor size={12} /> Console
            </button>
            <button type="button" className="text-xs text-rose-300 px-2 py-1 rounded border border-white/[0.08] hover:bg-white/[0.04]" onClick={showYaml}>
              YAML
            </button>
            <button type="button" onClick={onClose} className="p-2 rounded-lg text-slate-400 hover:bg-white/[0.06]"><X size={18} /></button>
          </div>
        </div>

        <div className="p-5 space-y-5">
          {isLoading && <div className="text-sm text-slate-400 flex items-center gap-2"><RefreshCw size={14} className="animate-spin" /> {t('loading')}</div>}
          {error && <div className="text-sm text-red-400">{error instanceof Error ? error.message : t('error_generic')}</div>}
          {err && <div className="text-sm text-red-400">{err}</div>}

          {detail && (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
                {[
                  ['Phase', detail.phase || detail.vm_power_state],
                  [t('ocp_col_project'), detail.namespace],
                  [t('ocp_col_worker'), detail.node_name || '—'],
                  ['CPU', `${detail.cpu_cores ?? detail.vm_cpu_count ?? '—'} core`],
                  [t('memory'), detail.memory_gb != null ? `${detail.memory_gb} GB` : `${detail.vm_memory_mb || '—'} MB`],
                  ['IP', detail.ip_address || detail.vm_guest_ip || '—'],
                  ['Guest OS', detail.guest_os || detail.os_type || '—'],
                  ['Host', detail.hostname || detail.vm_guest_hostname || '—'],
                  ['Machine', detail.machine_type || '—'],
                  ['Launcher', detail.launcher_pod || '—'],
                ].map(([l, v]) => (
                  <div key={String(l)} className="rounded-lg border border-white/[0.06] bg-cyber-deep/50 px-3 py-2">
                    <div className="text-slate-500">{l}</div>
                    <div className={`font-medium truncate ${l === 'Phase' ? statusColor(String(v)) : 'text-white'}`}>{String(v)}</div>
                  </div>
                ))}
              </div>

              <div>
                <div className="text-xs uppercase text-slate-500 mb-2">{t('ocp_disks_pvc')}</div>
                {(detail.disks || []).length === 0 && <div className="text-xs text-slate-500">{t('ocp_no_disk')}</div>}
                <div className="space-y-2">
                  {(detail.disks || []).map((d: { name: string; source?: string; bus?: string; image?: string; pvc?: any; pv?: any }) => (
                    <div key={d.name} className="rounded-lg border border-white/[0.06] px-3 py-2 text-xs space-y-1">
                      <div className="flex justify-between gap-2">
                        <span className="text-white font-medium">{d.name}</span>
                        <span className="text-slate-500">{d.source || '—'}{d.bus ? ` · ${d.bus}` : ''}</span>
                      </div>
                      {d.image && <div className="text-slate-500 truncate">image: {d.image}</div>}
                      {d.pvc && !d.pvc.error && (
                        <div className="text-slate-300">
                          PVC <span className="text-white">{d.pvc.namespace}/{d.pvc.name}</span>
                          {' · '}<span className={statusColor(d.pvc.phase)}>{d.pvc.phase}</span>
                          {d.pvc.capacity_gb != null ? ` · ${d.pvc.capacity_gb} GB` : ''}
                          {d.pvc.storage_class ? ` · ${d.pvc.storage_class}` : ''}
                        </div>
                      )}
                      {d.pv && !d.pv.error && (
                        <div className="text-slate-400">
                          PV <span className="text-white">{d.pv.name}</span>
                          {' · '}<span className={statusColor(d.pv.phase)}>{d.pv.phase}</span>
                          {d.pv.reclaim ? ` · reclaim ${d.pv.reclaim}` : ''}
                          {d.pv.capacity_gb != null ? ` · ${d.pv.capacity_gb} GB` : ''}
                        </div>
                      )}
                      {(d.pvc?.error || d.pv?.error) && (
                        <div className="text-amber-400">{d.pvc?.error || d.pv?.error}</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <div className="text-xs uppercase text-slate-500 mb-2">{t('ocp_nics')}</div>
                {(detail.nics || detail.vm_network_info || []).length === 0 && (
                  <div className="text-xs text-slate-500">{t('ocp_no_nic')}</div>
                )}
                <div className="space-y-1.5">
                  {(detail.nics || detail.vm_network_info || []).map((n: any, i: number) => (
                    <div key={n.name || i} className="rounded-lg border border-white/[0.06] px-3 py-2 text-xs flex flex-wrap justify-between gap-2">
                      <span className="text-white">{n.name || 'nic'}</span>
                      <span className="text-slate-400">
                        {n.ip_address || n.ips?.[0]?.address || '—'}
                        {n.mac ? ` · ${n.mac}` : ''}
                        {n.binding ? ` · ${n.binding}` : ''}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          <section className="rounded-xl border border-white/[0.06] p-4 space-y-3">
            <div className="flex items-center gap-2">
              <Camera size={14} className="text-sky-400" />
              <h3 className="text-sm font-semibold text-white">{t('ocp_snapshots')}</h3>
              <span className="text-[11px] text-slate-500">{snapshots.length}</span>
            </div>
            {isAdmin && (
              <div className="flex flex-wrap gap-2">
                <input
                  value={snapName}
                  onChange={(e) => setSnapName(e.target.value)}
                  placeholder={t('ocp_snap_name')}
                  className={`${inputCls} flex-1 min-w-[10rem]`}
                />
                <button
                  type="button"
                  disabled={busy}
                  className={btnCls}
                  onClick={() => run(() => api(`${base}/snapshots`, {
                    method: 'POST',
                    body: JSON.stringify({ snapshot_name: snapName.trim() || undefined }),
                  }))}
                >
                  <Camera size={12} /> {t('ocp_snap_title')}
                </button>
              </div>
            )}
            {snapshots.length === 0 ? (
              <p className="text-xs text-slate-500">{t('ocp_no_snapshots')}</p>
            ) : (
              <ul className="space-y-1.5">
                {snapshots.map((s) => (
                  <li key={s.name} className="rounded-lg border border-white/[0.06] px-3 py-2 text-xs flex flex-wrap items-center gap-2">
                    <span className="text-white font-medium truncate">{s.name}</span>
                    <span className={statusColor(s.phase || (s.ready ? 'ready' : 'pending'))}>
                      {s.phase || (s.ready ? 'Ready' : 'Pending')}
                    </span>
                    {s.created && <span className="text-slate-500">{s.created.replace('T', ' ').slice(0, 19)}</span>}
                    {isAdmin && (
                      <span className="ml-auto flex items-center gap-1">
                        <button
                          type="button"
                          disabled={busy || s.ready === false}
                          className="px-2 py-1 rounded border border-white/[0.08] text-slate-200 hover:bg-white/[0.06] disabled:opacity-40"
                          onClick={() => {
                            if (!window.confirm(t('ocp_snap_restore_confirm', { name: s.name }))) return
                            run(() => api(`${base}/snapshots/restore`, {
                              method: 'POST',
                              body: JSON.stringify({ snapshot_name: s.name }),
                            }))
                          }}
                        >
                          {t('ocp_snap_restore')}
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          title={t('ocp_snap_delete')}
                          className="p-1 rounded text-red-300 hover:bg-red-500/10"
                          onClick={() => {
                            if (!window.confirm(t('ocp_snap_delete_confirm', { name: s.name }))) return
                            run(() => api(`${base}/snapshots/${encodeURIComponent(s.name)}`, { method: 'DELETE' }))
                          }}
                        >
                          <Trash2 size={12} />
                        </button>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {isAdmin && !vmOff && snapshots.length > 0 && (
              <p className="text-[11px] text-amber-400/80">{t('ocp_snap_restore_off')}</p>
            )}
          </section>

          <section className="rounded-xl border border-white/[0.06] p-4 space-y-3">
            <div className="flex items-center gap-2">
              <Copy size={14} className="text-emerald-400" />
              <h3 className="text-sm font-semibold text-white">{t('ocp_clones')}</h3>
              <span className="text-[11px] text-slate-500">{clones.length}</span>
            </div>
            {isAdmin && (
              <div className="flex flex-wrap gap-2">
                <input
                  value={cloneTarget}
                  onChange={(e) => setCloneTarget(e.target.value)}
                  placeholder={t('ocp_target_vm')}
                  className={`${inputCls} flex-1 min-w-[10rem]`}
                />
                <button
                  type="button"
                  disabled={busy || !cloneTarget.trim()}
                  className={btnCls}
                  onClick={() => {
                    if (!window.confirm(t('ocp_clone_confirm', { from: name, to: cloneTarget.trim() }))) return
                    run(() => api(`${base}/clone`, {
                      method: 'POST',
                      body: JSON.stringify({ target_name: cloneTarget.trim() }),
                    }))
                  }}
                >
                  <Copy size={12} /> {t('ocp_clone_title')}
                </button>
              </div>
            )}
            {clones.length === 0 ? (
              <p className="text-xs text-slate-500">{t('ocp_no_clones')}</p>
            ) : (
              <ul className="space-y-1.5">
                {clones.map((c) => (
                  <li key={c.name} className="rounded-lg border border-white/[0.06] px-3 py-2 text-xs flex flex-wrap items-center gap-2">
                    <span className="text-white font-medium truncate">{c.name}</span>
                    {c.target && <span className="text-slate-400">→ {c.target}</span>}
                    <span className={statusColor(c.phase)}>{c.phase || '—'}</span>
                    {c.created && <span className="text-slate-500">{c.created.replace('T', ' ').slice(0, 19)}</span>}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {isAdmin && (
            <section className="rounded-xl border border-white/[0.06] p-4 space-y-3">
              <div className="flex items-center gap-2">
                <HardDrive size={14} className="text-amber-400" />
                <h3 className="text-sm font-semibold text-white">{t('ocp_disk_dv')}</h3>
              </div>
              <p className="text-[11px] text-slate-500">{t('ocp_disk_dv_hint')}</p>
              <div className="grid sm:grid-cols-2 gap-2">
                <input value={diskName} onChange={(e) => setDiskName(e.target.value)} placeholder={t('ocp_disk_name')} className={inputCls} />
                <input value={diskSize} onChange={(e) => setDiskSize(e.target.value)} placeholder={t('ocp_size_20')} className={inputCls} />
                <select value={storageClass} onChange={(e) => setStorageClass(e.target.value)} className={`${inputCls} sm:col-span-2`}>
                  <option value="">{t('ocp_sc_cluster_default')}</option>
                  {classes.map((sc) => (
                    <option key={sc.name} value={sc.name}>
                      {sc.name}{sc.default ? t('ocp_sc_default_paren') : ''}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="button"
                disabled={busy || !diskName.trim()}
                className={btnCls}
                onClick={() => {
                  if (!window.confirm(t('ocp_disk_add_confirm', { name: diskName.trim() }))) return
                  run(() => api(`${base}/disk`, {
                    method: 'POST',
                    body: JSON.stringify({
                      disk_name: diskName.trim(),
                      size: diskSize.trim() || '20Gi',
                      storage_class: storageClass || undefined,
                    }),
                  }))
                }}
              >
                <HardDrive size={12} /> {t('ocp_add_disk')}
              </button>
            </section>
          )}
        </div>
      </div>

      {yamlText != null && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4" onClick={() => setYamlText(null)}>
          <div className="w-full max-w-3xl max-h-[85vh] bg-cyber-card border border-white/[0.08] rounded-xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
              <span className="text-sm text-white">YAML</span>
              <button type="button" onClick={() => setYamlText(null)} className="text-slate-400"><X size={16} /></button>
            </div>
            <pre className="p-4 text-[11px] text-cyan-100/90 overflow-auto max-h-[75vh] font-mono whitespace-pre-wrap">{yamlText}</pre>
          </div>
        </div>
      )}
    </div>
  )
}
