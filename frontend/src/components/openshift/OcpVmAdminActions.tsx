/**
 * Admin-only KubeVirt VM yaşam döngüsü: güç, klon, sil, snapshot, disk, network, ISO/CD-ROM.
 * Menü createPortal + fixed — tablo overflow-x-auto altında kesilmesin.
 * ⋯ düğmesi VEYA satıra sağ tık (contextPos) aynı menüyü açar.
 */
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Play, Square, RotateCcw, Copy, Trash2, Camera, HardDrive, Network, MoreHorizontal, X, RefreshCw,
  Disc3, Monitor,
} from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useAuth } from '../../auth/AuthContext'
import { useT } from '../../i18n/LocaleProvider'
import OcpVmIsoPanel from './OcpVmIsoPanel'

type Vm = { name: string; namespace: string; phase?: string; printable_status?: string }

type Props = {
  clusterId: number
  vm: Vm
  onConsole?: () => void
  /** Satıra sağ tıklama konumu (tarayıcı koordinatı); null = kapalı. */
  contextPos?: { x: number; y: number } | null
  onContextClose?: () => void
}

type MenuPos = { top: number; left: number; openUp: boolean }

async function api(path: string, init?: RequestInit) {
  const r = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.[0]?.msg || `HTTP ${r.status}`)
  return data
}

const MENU_W = 192
const MENU_H = 330

export default function OcpVmAdminActions({ clusterId, vm, onConsole, contextPos, onContextClose }: Props) {
  const t = useT()
  const { user } = useAuth()
  const isAdmin = Boolean(user?.is_admin || user?.role === 'admin')
  const qc = useQueryClient()
  const moreRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const [menu, setMenu] = useState(false)
  const [menuPos, setMenuPos] = useState<MenuPos | null>(null)
  const [panel, setPanel] = useState<'clone' | 'snapshot' | 'disk' | 'network' | 'pvc' | 'iso' | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [target, setTarget] = useState(`${vm.name}-clone`)
  const [snapName, setSnapName] = useState('')
  const [diskName, setDiskName] = useState(`${vm.name}-disk2`)
  const [size, setSize] = useState('20Gi')
  const [nad, setNad] = useState('')
  const [pvcName, setPvcName] = useState(`${vm.name}-pvc`)
  const [storageClass, setStorageClass] = useState('')

  const placeMenu = () => {
    const el = moreRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const spaceBelow = window.innerHeight - r.bottom
    const openUp = spaceBelow < MENU_H && r.top > spaceBelow
    const top = openUp ? r.top - 4 : r.bottom + 4
    let left = r.right - MENU_W
    left = Math.max(8, Math.min(left, window.innerWidth - MENU_W - 8))
    setMenuPos({ top, left, openUp })
  }

  const ctxOpen = Boolean(contextPos)
  const closeAll = () => {
    setMenu(false)
    setMenuPos(null)
    onContextClose?.()
  }

  const toggleMenu = () => {
    if (ctxOpen) onContextClose?.()
    setErr('')
    setMenu((v) => {
      const next = !v
      if (next) placeMenu()
      else setMenuPos(null)
      return next
    })
  }

  useEffect(() => {
    if (!menu && !ctxOpen) return
    if (!ctxOpen) placeMenu()
    const onScroll = () => (ctxOpen ? closeAll() : placeMenu())
    const onResize = () => (ctxOpen ? closeAll() : placeMenu())
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node
      if (moreRef.current?.contains(t) || menuRef.current?.contains(t)) return
      closeAll()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeAll()
    }
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onResize)
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onResize)
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [menu, ctxOpen])

  const { data: storage } = useQuery({
    queryKey: ['openshift-storage', clusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/storage`)
      if (!r.ok) return { storage_classes: [] as { name: string; default?: boolean }[] }
      return r.json()
    },
    enabled: isAdmin && (panel === 'disk' || panel === 'pvc'),
  })
  const classes: { name: string; default?: boolean }[] = storage?.storage_classes || []

  if (!isAdmin) return null

  const base = `/openshift/clusters/${clusterId}/kubevirt/vms/${encodeURIComponent(vm.namespace)}/${encodeURIComponent(vm.name)}`
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['openshift-kubevirt-vms', clusterId] })
    qc.invalidateQueries({ queryKey: ['openshift-vm-detail', clusterId, vm.namespace, vm.name] })
    qc.invalidateQueries({ queryKey: ['openshift-vm-snapshots', clusterId, vm.namespace, vm.name] })
    qc.invalidateQueries({ queryKey: ['openshift-vm-clones', clusterId, vm.namespace, vm.name] })
  }

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setErr('')
    try {
      await fn()
      refresh()
      setPanel(null)
      closeAll()
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('ocp_action_fail'))
    } finally {
      setBusy(false)
    }
  }

  const phase = (vm.phase || vm.printable_status || '').toLowerCase()
  const running = phase === 'running'

  const pick = (p: typeof panel) => {
    setPanel(p)
    closeAll()
  }

  const itemCls = 'w-full px-3 py-1.5 text-left text-slate-200 hover:bg-white/[0.05] inline-flex items-center gap-2 disabled:opacity-30 disabled:hover:bg-transparent'
  const power = (action: 'start' | 'stop' | 'restart') => {
    if (action === 'stop' && !window.confirm(t('ocp_stop_confirm', { name: vm.name }))) return
    if (action === 'restart' && !window.confirm(t('ocp_restart_vm_confirm', { name: vm.name }))) return
    run(() => api(`${base}/power`, { method: 'POST', body: JSON.stringify({ action }) }))
  }

  const menuItems = (
    <>
      <button type="button" disabled={busy || running} className={`${itemCls} text-emerald-300`} onClick={() => power('start')}>
        <Play size={11} /> {t('start')}
      </button>
      <button type="button" disabled={busy || !running} className={`${itemCls} text-cyan-300`} onClick={() => power('restart')}>
        <RotateCcw size={11} /> {t('restart')}
      </button>
      <button type="button" disabled={busy || !running} className={`${itemCls} text-amber-300`} onClick={() => power('stop')}>
        <Square size={11} /> {t('stop')}
      </button>
      {onConsole && running && (
        <button type="button" className={`${itemCls} text-violet-300`} onClick={() => { closeAll(); onConsole() }}>
          <Monitor size={11} /> {t('ocp_console_novnc')}
        </button>
      )}
      <div className="my-1 border-t border-white/[0.06]" />
      <button type="button" className="w-full px-3 py-1.5 text-left text-slate-200 hover:bg-white/[0.05] inline-flex items-center gap-2" onClick={() => pick('clone')}>
        <Copy size={11} /> {t('ocp_clone')}
      </button>
      <button type="button" className="w-full px-3 py-1.5 text-left text-slate-200 hover:bg-white/[0.05] inline-flex items-center gap-2" onClick={() => pick('snapshot')}>
        <Camera size={11} /> {t('ocp_snapshot')}
      </button>
      <button type="button" className="w-full px-3 py-1.5 text-left text-slate-200 hover:bg-white/[0.05] inline-flex items-center gap-2" onClick={() => pick('disk')}>
        <HardDrive size={11} /> {t('ocp_add_disk')}
      </button>
      <button type="button" className="w-full px-3 py-1.5 text-left text-slate-200 hover:bg-white/[0.05] inline-flex items-center gap-2" onClick={() => pick('network')}>
        <Network size={11} /> {t('ocp_net_multus')}
      </button>
      <button type="button" className="w-full px-3 py-1.5 text-left text-slate-200 hover:bg-white/[0.05] inline-flex items-center gap-2" onClick={() => pick('iso')}>
        <Disc3 size={11} /> {t('ocp_iso')}
      </button>
      <button type="button" className="w-full px-3 py-1.5 text-left text-slate-200 hover:bg-white/[0.05] inline-flex items-center gap-2" onClick={() => pick('pvc')}>
        <HardDrive size={11} /> {t('ocp_create_pvc')}
      </button>
      <button
        type="button"
        className="w-full px-3 py-1.5 text-left text-red-300 hover:bg-red-500/10 inline-flex items-center gap-2"
        onClick={() => {
          if (!window.confirm(t('ocp_delete_vm_confirm', { ns: vm.namespace, name: vm.name }))) return
          run(() => api(base, { method: 'DELETE' }))
        }}
      >
        <Trash2 size={11} /> {t('ocp_delete_vm')}
      </button>
    </>
  )

  return (
    <div className="inline-flex items-center gap-1">
      <button
        ref={moreRef}
        type="button"
        title={t('ocp_more')}
        onClick={toggleMenu}
        className="p-1 rounded text-slate-400 hover:bg-white/[0.06]"
      >
        <MoreHorizontal size={12} />
      </button>

      {(ctxOpen || (menu && menuPos)) && createPortal(
        <div
          ref={menuRef}
          onContextMenu={(e) => { e.preventDefault(); e.stopPropagation() }}
          className="w-48 rounded-lg border border-white/[0.08] bg-cyber-card shadow-2xl py-1 text-[11px]"
          style={ctxOpen && contextPos ? {
            position: 'fixed',
            zIndex: 80,
            left: Math.max(8, Math.min(contextPos.x, window.innerWidth - MENU_W - 8)),
            top: Math.max(8, Math.min(contextPos.y, window.innerHeight - MENU_H - 8)),
          } : menuPos ? {
            position: 'fixed',
            zIndex: 80,
            left: menuPos.left,
            ...(menuPos.openUp
              ? { bottom: window.innerHeight - menuPos.top, top: 'auto' }
              : { top: menuPos.top }),
          } : undefined}
        >
          {menuItems}
        </div>,
        document.body,
      )}

      {panel === 'iso' && createPortal(
        <OcpVmIsoPanel
          clusterId={clusterId}
          vm={vm}
          running={running}
          onClose={() => setPanel(null)}
          onChanged={refresh}
        />,
        document.body,
      )}

      {panel && panel !== 'iso' && createPortal(
        <div className="fixed inset-0 bg-black/55 z-[90] flex items-center justify-center p-4" onClick={() => !busy && setPanel(null)} onContextMenu={(e) => e.stopPropagation()}>
          <div className="bg-cyber-card border border-white/[0.08] rounded-xl w-full max-w-sm p-4 space-y-3" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div className="text-sm text-white font-medium">
                {panel === 'clone' && t('ocp_clone_title')}
                {panel === 'snapshot' && t('ocp_snap_title')}
                {panel === 'disk' && t('ocp_disk_dv')}
                {panel === 'network' && t('ocp_attach_nad')}
                {panel === 'pvc' && t('ocp_create_pvc')}
              </div>
              <button type="button" onClick={() => setPanel(null)} className="text-slate-400"><X size={16} /></button>
            </div>
            <p className="text-[11px] text-slate-500">{vm.namespace}/{vm.name}</p>
            {panel === 'clone' && (
              <input value={target} onChange={(e) => setTarget(e.target.value)} placeholder={t('ocp_target_vm')} className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white" />
            )}
            {panel === 'snapshot' && (
              <input value={snapName} onChange={(e) => setSnapName(e.target.value)} placeholder={t('ocp_snap_name')} className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white" />
            )}
            {panel === 'disk' && (
              <>
                <input value={diskName} onChange={(e) => setDiskName(e.target.value)} placeholder={t('ocp_disk_name')} className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white" />
                <input value={size} onChange={(e) => setSize(e.target.value)} placeholder={t('ocp_size_20')} className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white" />
                <select value={storageClass} onChange={(e) => setStorageClass(e.target.value)} className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white">
                  <option value="">{t('ocp_sc_cluster_default')}</option>
                  {classes.map((sc) => (
                    <option key={sc.name} value={sc.name}>{sc.name}{sc.default ? t('ocp_sc_default_paren') : ''}</option>
                  ))}
                </select>
              </>
            )}
            {panel === 'network' && (
              <input value={nad} onChange={(e) => setNad(e.target.value)} placeholder={t('ocp_nad_name')} className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white" />
            )}
            {panel === 'pvc' && (
              <>
                <input value={pvcName} onChange={(e) => setPvcName(e.target.value)} placeholder={t('ocp_pvc_name')} className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white" />
                <input value={size} onChange={(e) => setSize(e.target.value)} placeholder={t('ocp_size_10')} className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white" />
                <select value={storageClass} onChange={(e) => setStorageClass(e.target.value)} className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white">
                  <option value="">{t('ocp_sc_cluster_default')}</option>
                  {classes.map((sc) => (
                    <option key={sc.name} value={sc.name}>{sc.name}{sc.default ? t('ocp_sc_default_paren') : ''}</option>
                  ))}
                </select>
              </>
            )}
            {err && <div className="text-xs text-red-400">{err}</div>}
            <button
              type="button"
              disabled={busy}
              className="w-full py-2 rounded-lg bg-rose-600 text-white text-sm font-medium disabled:opacity-50 inline-flex items-center justify-center gap-1.5"
              onClick={() => {
                if (panel === 'clone') {
                  if (!window.confirm(t('ocp_clone_confirm', { from: vm.name, to: target }))) return
                  run(() => api(`${base}/clone`, { method: 'POST', body: JSON.stringify({ target_name: target }) }))
                } else if (panel === 'snapshot') {
                  run(() => api(`${base}/snapshots`, { method: 'POST', body: JSON.stringify({ snapshot_name: snapName || undefined }) }))
                } else if (panel === 'disk') {
                  if (!window.confirm(t('ocp_disk_add_confirm', { name: diskName }))) return
                  run(() => api(`${base}/disk`, { method: 'POST', body: JSON.stringify({ disk_name: diskName, size, storage_class: storageClass || undefined }) }))
                } else if (panel === 'network') {
                  run(() => api(`${base}/network`, { method: 'POST', body: JSON.stringify({ nad_name: nad }) }))
                } else if (panel === 'pvc') {
                  run(() => api(`/openshift/clusters/${clusterId}/kubevirt/pvc`, {
                    method: 'POST',
                    body: JSON.stringify({ namespace: vm.namespace, name: pvcName, size, storage_class: storageClass || undefined }),
                  }))
                }
              }}
            >
              {busy && <RefreshCw size={12} className="animate-spin" />} {t('apply')}
            </button>
          </div>
        </div>,
        document.body,
      )}
    </div>
  )
}
